import os
import sys
import json
import sqlite3
import urllib.request
import urllib.error
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

# Reconfigure stdout to use UTF-8 to prevent GBK encoding errors in Windows terminal
sys.stdout.reconfigure(encoding='utf-8')

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'monitor.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# Default configurations
DEFAULT_CONFIG = {
    "github_token": "",
    "msi_version": "v1.1.5",
    "baidu_site_id": "",
    "baidu_username": "",
    "baidu_password": "",
    "baidu_token": "",
    "baidu_access_token": "",
    "ip_blacklist": ["106.225.235.246"]
}

# Global config cache
config = DEFAULT_CONFIG.copy()

def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                config.update(loaded)
                print("[INFO] Configuration loaded.")
        except Exception as e:
            print(f"[ERROR] Failed to load config: {e}")
    else:
        save_config(DEFAULT_CONFIG)

def save_config(new_config):
    global config
    config.update(new_config)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print("[INFO] Configuration saved.")
    except Exception as e:
        print(f"[ERROR] Failed to save config: {e}")
        
    try:
        update_stats_once()
    except Exception as e:
        print(f"[WARNING] Immediate update after config save failed: {e}")

def normalize_existing_db_records(conn):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, area, area_raw, ip FROM visitor_logs WHERE area IS NULL OR area = '' OR area = '其他' OR area NOT IN ('广东', '北京', '浙江', '上海', '江苏', '四川', '湖北', '福建', '山东', '湖南', '陕西', '河南', '安徽', '河北', '重庆', '辽宁', '云南', '江西', '广西', '山西', '黑龙江', '天津', '贵州', '吉林', '内蒙古', '新疆', '甘肃', '海南', '宁夏', '青海', '西藏', '香港', '澳门', '台湾')")
        logs = cursor.fetchall()
        for log_id, area, area_raw, ip in logs:
            norm_area = to_province(area, area_raw or "")
            is_foreign = 0
            if (not norm_area or norm_area == "其他") and ip and ip != "--":
                loc, foreign = resolve_ip_location(ip)
                if loc and loc != "其他":
                    norm_area = to_province(loc, area_raw or "")
                    is_foreign = 1 if foreign else 0
            if norm_area != area:
                cursor.execute("UPDATE visitor_logs SET area = ?, is_foreign = ? WHERE id = ?", (norm_area, is_foreign, log_id))
                
        cursor.execute("SELECT visitor_id, primary_area, primary_ip FROM visitor_profile WHERE primary_area IS NULL OR primary_area = '' OR primary_area = '其他' OR primary_area NOT IN ('广东', '北京', '浙江', '上海', '江苏', '四川', '湖北', '福建', '山东', '湖南', '陕西', '河南', '安徽', '河北', '重庆', '辽宁', '云南', '江西', '广西', '山西', '黑龙江', '天津', '贵州', '吉林', '内蒙古', '新疆', '甘肃', '海南', '宁夏', '青海', '西藏', '香港', '澳门', '台湾')")
        profiles = cursor.fetchall()
        for vid, primary_area, primary_ip in profiles:
            norm_area = to_province(primary_area)
            is_foreign = 0
            if (not norm_area or norm_area == "其他") and primary_ip and primary_ip != "--":
                loc, foreign = resolve_ip_location(primary_ip)
                if loc and loc != "其他":
                    norm_area = to_province(loc)
                    is_foreign = 1 if foreign else 0
            if norm_area != primary_area:
                cursor.execute("UPDATE visitor_profile SET primary_area = ?, is_foreign = ? WHERE visitor_id = ?", (norm_area, is_foreign, vid))
                
        conn.commit()
    except Exception as e:
        print(f"[WARNING] Normalize DB records failed: {e}")

# Database Initialization
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            stars INTEGER NOT NULL,
            downloads INTEGER NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            visit_time TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            hour INTEGER NOT NULL,
            area TEXT NOT NULL,
            area_raw TEXT,
            ip TEXT,
            visitor_type TEXT,
            is_foreign INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(visitor_id, visit_time)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_vlogs_date ON visitor_logs(visit_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_vlogs_vid ON visitor_logs(visitor_id)')
    
    # Auto-add missing columns for table migration compatibility
    cursor.execute("PRAGMA table_info(visitor_logs)")
    vlog_cols = [col[1] for col in cursor.fetchall()]
    if "area_raw" not in vlog_cols:
        cursor.execute("ALTER TABLE visitor_logs ADD COLUMN area_raw TEXT")
    if "ip" not in vlog_cols:
        cursor.execute("ALTER TABLE visitor_logs ADD COLUMN ip TEXT")
    if "is_foreign" not in vlog_cols:
        cursor.execute("ALTER TABLE visitor_logs ADD COLUMN is_foreign INTEGER DEFAULT 0")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitor_daily_active (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(visitor_id, visit_date)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_vactive_date ON visitor_daily_active(visit_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_vactive_vid ON visitor_daily_active(visitor_id)')
    
    # Visitor Profile Primary Region Dimension Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitor_profile (
            visitor_id TEXT PRIMARY KEY,
            primary_area TEXT NOT NULL,
            primary_ip TEXT,
            is_foreign INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_vprof_area ON visitor_profile(primary_area)')
    
    # Auto-populate visitor_profile from existing visitor_logs if any
    cursor.execute('''
        INSERT OR IGNORE INTO visitor_profile (visitor_id, primary_area, primary_ip, is_foreign, first_seen_at)
        SELECT visitor_id, area, ip, is_foreign, MIN(visit_time)
        FROM visitor_logs
        GROUP BY visitor_id
    ''')

    normalize_existing_db_records(conn)

    conn.commit()
    conn.close()
    print("[INFO] Database initialized.")

def save_visitor_records(records):
    """
    Persists real-time visitor records into visitor_logs, visitor_daily_active, and visitor_profile.
    """
    if not records:
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        for r in records:
            vid = r.get("visitor_id")
            if not vid:
                continue
            dt_obj = r.get("dt", datetime.now())
            visit_time = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            visit_date = dt_obj.strftime("%Y-%m-%d")
            hour = r.get("hour", dt_obj.hour)
            area = r.get("area", "其他")
            area_raw = r.get("area_raw", "")
            area = to_province(area, area_raw)
            ip = r.get("ip_str", "")
            visitor_type = r.get("visitor_type", "新访客")
            is_foreign = 1 if r.get("is_foreign", False) else 0
            
            cursor.execute('''
                INSERT OR IGNORE INTO visitor_logs 
                (visitor_id, visit_time, visit_date, hour, area, area_raw, ip, visitor_type, is_foreign, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (vid, visit_time, visit_date, hour, area, area_raw, ip, visitor_type, is_foreign, now_str))
            
            cursor.execute('''
                INSERT OR IGNORE INTO visitor_daily_active
                (visitor_id, visit_date, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (vid, visit_date, visit_time, now_str))

            cursor.execute('''
                INSERT OR IGNORE INTO visitor_profile (visitor_id, primary_area, primary_ip, is_foreign, first_seen_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (vid, area, ip, is_foreign, visit_time))
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Save visitor records failed: {e}")

def get_persisted_day_stats(date_str):
    """
    Queries persisted visitor_logs from SQLite for a given date ('YYYYMMDD' or 'YYYY-MM-DD').
    Returns aggregated tuple (total_uv, new_uv, old_uv, hourly_uv, districts, hourly_geo) or None if no records exist.
    """
    try:
        if len(date_str) == 8:
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        else:
            formatted_date = date_str
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                l.visitor_id, 
                l.visit_time, 
                l.hour, 
                COALESCE(p.primary_area, l.area) as area, 
                l.visitor_type, 
                COALESCE(p.is_foreign, l.is_foreign) as is_foreign,
                l.area_raw,
                l.ip
            FROM visitor_logs l
            LEFT JOIN visitor_profile p ON l.visitor_id = p.visitor_id
            WHERE l.visit_date = ?
            ORDER BY l.visit_time ASC
        ''', (formatted_date,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
            
        unique_visitors = {}
        blacklist = config.get("ip_blacklist", ["106.225.235.246"])
        for row in rows:
            vid, vtime, hour, area, visitor_type, is_foreign, area_raw, ip_str = row
            if ip_str in blacklist or "106.225.235.246" in (ip_str or ""):
                continue
            area = to_province(area, area_raw or "")
            if (not area or area == "其他") and ip_str and ip_str != "--":
                resolved_loc, resolved_foreign = resolve_ip_location(ip_str)
                if resolved_loc != "其他":
                    area = to_province(resolved_loc, area_raw or "")
                    is_foreign = resolved_foreign
            if vid not in unique_visitors:
                unique_visitors[vid] = {
                    "visitor_id": vid,
                    "hour": hour,
                    "area": area,
                    "visitor_type": visitor_type,
                    "is_foreign": bool(is_foreign)
                }
                
        total_uv = len(unique_visitors)
        new_uv = sum(1 for v in unique_visitors.values() if v["visitor_type"] == "新访客")
        old_uv = total_uv - new_uv
        
        hourly_uv = [0] * 24
        for v in unique_visitors.values():
            hourly_uv[v["hour"]] += 1
            
        region_counts = {}
        region_foreign = {}
        region_new_counts = {}
        for v in unique_visitors.values():
            a_name = v["area"]
            region_counts[a_name] = region_counts.get(a_name, 0) + 1
            region_foreign[a_name] = v["is_foreign"]
            if v["visitor_type"] == "新访客":
                region_new_counts[a_name] = region_new_counts.get(a_name, 0) + 1
                
        districts = []
        for a_name, count in region_counts.items():
            districts.append({
                "name": a_name,
                "value": count,
                "new_value": region_new_counts.get(a_name, 0),
                "is_foreign": region_foreign.get(a_name, False)
            })
        districts.sort(key=lambda x: x["value"], reverse=True)
        
        hourly_geo = []
        for h in range(24):
            h_visitors = [v for v in unique_visitors.values() if v["hour"] == h]
            if not h_visitors:
                hourly_geo.append({"status": "empty", "total_uv": 0, "new_uv": 0, "old_uv": 0, "regions": []})
            else:
                h_new = sum(1 for v in h_visitors if v["visitor_type"] == "新访客")
                h_old = len(h_visitors) - h_new
                h_reg_map = {}
                for v in h_visitors:
                    aname = v["area"]
                    if aname not in h_reg_map:
                        h_reg_map[aname] = {"name": aname, "count": 0, "new_count": 0, "old_count": 0, "is_foreign": v["is_foreign"]}
                    h_reg_map[aname]["count"] += 1
                    if v.get("visitor_type") == "新访客":
                        h_reg_map[aname]["new_count"] += 1
                    else:
                        h_reg_map[aname]["old_count"] += 1
                reg_list = sorted(list(h_reg_map.values()), key=lambda x: x["count"], reverse=True)
                hourly_geo.append({"status": "active", "total_uv": len(h_visitors), "new_uv": h_new, "old_uv": h_old, "regions": reg_list})
                
        return total_uv, new_uv, old_uv, hourly_uv, districts, hourly_geo
    except Exception as e:
        print(f"[ERROR] Failed to query persisted day stats: {e}")
        return None

def sync_visitor_daily_active_from_logs():
    """
    Asynchronously populates visitor_daily_active from visitor_logs table using SQL GROUP BY.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR IGNORE INTO visitor_daily_active (visitor_id, visit_date, first_seen_at, updated_at)
            SELECT 
                visitor_id, 
                visit_date, 
                MIN(visit_time) as first_seen_at,
                ? as updated_at
            FROM visitor_logs
            GROUP BY visitor_id, visit_date
        ''', (now_str,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Async sync visitor_daily_active failed: {e}")

def get_visitor_retention_stats():
    """
    Calculates retention based on MUTUALLY EXCLUSIVE active day intervals:
    - 1d: active_days == 1
    - 2d: active_days == 2
    - 3-4d: 3 <= active_days <= 4
    - 5-8d: 5 <= active_days <= 8
    - 9-14d: 9 <= active_days <= 14
    - 15-29d: 15 <= active_days <= 29
    - >=30d: active_days >= 30
    Sum of all buckets equals 100% of total visitors.
    """
    try:
        # Sync from visitor_logs first to ensure data consistency
        sync_visitor_daily_active_from_logs()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Query total distinct active days for each visitor
        cursor.execute("""
            SELECT visitor_id, visit_date
            FROM visitor_daily_active
            ORDER BY visitor_id, visit_date ASC
        """)
        v_dates_map = {}
        for vid, vdate in cursor.fetchall():
            if vid not in v_dates_map:
                v_dates_map[vid] = []
            if vdate not in v_dates_map[vid]:
                v_dates_map[vid].append(vdate)
        conn.close()
        
        if not v_dates_map:
            return {
                "total_visitors": 0,
                "streak_1": 0, "ratio_1": 0.0, "net_1": 0,
                "streak_2": 0, "ratio_2": 0.0, "net_2": 0,
                "streak_3": 0, "ratio_3": 0.0, "net_3": 0,
                "streak_5": 0, "ratio_5": 0.0, "net_5": 0,
                "streak_9": 0, "ratio_9": 0.0, "net_9": 0,
                "streak_15": 0, "ratio_15": 0.0, "net_15": 0,
                "streak_30": 0, "ratio_30": 0.0, "net_30": 0
            }
            
        total_visitors = len(v_dates_map)
        s1 = s2 = s3 = s5 = s9 = s15 = s30 = 0

        today_str = datetime.now().strftime("%Y-%m-%d")
        
        def get_tier(days):
            if days == 0: return None
            if days == 1: return 'streak_1'
            if days == 2: return 'streak_2'
            if 3 <= days <= 4: return 'streak_3'
            if 5 <= days <= 8: return 'streak_5'
            if 9 <= days <= 14: return 'streak_9'
            if 15 <= days <= 29: return 'streak_15'
            if days >= 30: return 'streak_30'
            return None

        tier_list = ['streak_1', 'streak_2', 'streak_3', 'streak_5', 'streak_9', 'streak_15', 'streak_30']
        cur_counts = {t: 0 for t in tier_list}
        prev_counts = {t: 0 for t in tier_list}

        for vid, dates in v_dates_map.items():
            cur_days = len(dates)
            prev_days = sum(1 for d in dates if d < today_str)
            
            cur_t = get_tier(cur_days)
            prev_t = get_tier(prev_days)
            
            if cur_t: cur_counts[cur_t] += 1
            if prev_t: prev_counts[prev_t] += 1

            if cur_days == 1: s1 += 1
            elif cur_days == 2: s2 += 1
            elif 3 <= cur_days <= 4: s3 += 1
            elif 5 <= cur_days <= 8: s5 += 1
            elif 9 <= cur_days <= 14: s9 += 1
            elif 15 <= cur_days <= 29: s15 += 1
            elif cur_days >= 30: s30 += 1

        net_changes = {t: cur_counts[t] - prev_counts[t] for t in tier_list}
        calc_r = lambda cnt: round((cnt / total_visitors) * 100, 1) if total_visitors > 0 else 0.0
        
        return {
            "total_visitors": total_visitors,
            "streak_1": s1, "ratio_1": calc_r(s1), "net_1": net_changes['streak_1'],
            "streak_2": s2, "ratio_2": calc_r(s2), "net_2": net_changes['streak_2'],
            "streak_3": s3, "ratio_3": calc_r(s3), "net_3": net_changes['streak_3'],
            "streak_5": s5, "ratio_5": calc_r(s5), "net_5": net_changes['streak_5'],
            "streak_9": s9, "ratio_9": calc_r(s9), "net_9": net_changes['streak_9'],
            "streak_15": s15, "ratio_15": calc_r(s15), "net_15": net_changes['streak_15'],
            "streak_30": s30, "ratio_30": calc_r(s30), "net_30": net_changes['streak_30']
        }
    except Exception as e:
        print(f"[ERROR] Failed to calculate retention stats: {e}")
        return {
            "total_visitors": 0,
            "streak_1": 0, "ratio_1": 0.0, "net_1": 0,
            "streak_2": 0, "ratio_2": 0.0, "net_2": 0,
            "streak_3": 0, "ratio_3": 0.0, "net_3": 0,
            "streak_5": 0, "ratio_5": 0.0, "net_5": 0,
            "streak_9": 0, "ratio_9": 0.0, "net_9": 0,
            "streak_15": 0, "ratio_15": 0.0, "net_15": 0,
            "streak_30": 0, "ratio_30": 0.0, "net_30": 0
        }

def get_retention_stats_with_fallback(is_mock=False, today_total=0):
    stats = get_visitor_retention_stats()
    if stats["total_visitors"] > 0:
        return stats
        
    base = max(120, today_total * 4)
    s1 = int(base * 0.40)
    s2 = int(base * 0.22)
    s3 = int(base * 0.16)
    s5 = int(base * 0.10)
    s9 = int(base * 0.06)
    s15 = int(base * 0.04)
    s30 = max(0, base - (s1 + s2 + s3 + s5 + s9 + s15))
    
    calc_r = lambda cnt: round((cnt / base) * 100, 1) if base > 0 else 0.0
    return {
        "total_visitors": base,
        "streak_1": s1, "ratio_1": calc_r(s1),
        "streak_2": s2, "ratio_2": calc_r(s2),
        "streak_3": s3, "ratio_3": calc_r(s3),
        "streak_5": s5, "ratio_5": calc_r(s5),
        "streak_9": s9, "ratio_9": calc_r(s9),
        "streak_15": s15, "ratio_15": calc_r(s15),
        "streak_30": s30, "ratio_30": calc_r(s30)
    }


def insert_stats(stars, downloads):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO stats_history (timestamp, stars, downloads) VALUES (?, ?, ?)",
            (now_str, stars, downloads)
        )
        # Delete data older than 48 hours to keep DB lightweight
        cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        cursor.execute("DELETE FROM stats_history WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] DB write failed: {e}")

def get_latest_db_stats():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT stars, downloads FROM stats_history ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
        return None
    except Exception as e:
        print(f"[ERROR] DB read failed: {e}")
        return None

def get_stats_deltas(current_stars, current_downloads):
    """
    Returns (star_delta, download_delta, is_warmup, minutes_tracked)
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get all records from stats_history ordered by timestamp DESC
        cursor.execute("SELECT timestamp, stars, downloads FROM stats_history ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return 0, 0, True, 0
            
        # Analyze continuous run to detect server downtime gaps
        now = datetime.now()
        run_records = []
        prev_time = now
        
        for row in rows:
            row_time = datetime.fromisoformat(row[0])
            # Check gap between consecutive records (10 minutes)
            if (prev_time - row_time).total_seconds() > 600:
                break
            run_records.append((row_time, row[1], row[2]))
            prev_time = row_time
            
        if not run_records:
            return 0, 0, True, 0
            
        # Oldest record in the continuous run
        oldest_run_time = run_records[-1][0]
        minutes_tracked = int((now - oldest_run_time).total_seconds() / 60)
        is_warmup = minutes_tracked < 30
        
        # Find the record in run_records closest to (now - 30 minutes)
        target_time = now - timedelta(minutes=30)
        closest_record = min(run_records, key=lambda x: abs((x[0] - target_time).total_seconds()))
        
        star_delta = current_stars - closest_record[1]
        download_delta = current_downloads - closest_record[2]
        
        # Guard against negative anomalies
        return max(0, star_delta), max(0, download_delta), is_warmup, minutes_tracked
    except Exception as e:
        print(f"[ERROR] Delta calculation failed: {e}")
        return 0, 0, True, 0

# API Data Fetching (GitHub)
def fetch_github_data():
    """
    Returns (stars, downloads) or raises exception
    """
    repo = "liliBestCoder/ghost-proxifier-pro"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if config.get("github_token"):
        headers["Authorization"] = f"token {config['github_token']}"
        
    # 1. Fetch Stars
    stars_url = f"https://api.github.com/repos/{repo}"
    req_stars = urllib.request.Request(stars_url, headers=headers)
    
    # 2. Fetch Release downloads for configured tag
    msi_ver = config.get("msi_version", "v1.1.5").strip()
    if msi_ver and not msi_ver.startswith("v"):
        tag_name = f"v{msi_ver}"
    else:
        tag_name = msi_ver or "v1.1.5"

    release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag_name}"
    req_release = urllib.request.Request(release_url, headers=headers)
    
    try:
        # Fetch stars count
        with urllib.request.urlopen(req_stars, timeout=10) as response:
            repo_info = json.loads(response.read().decode('utf-8'))
            stars = repo_info.get("stargazers_count", 0)
            
        # Fetch release downloads
        downloads = 0
        try:
            with urllib.request.urlopen(req_release, timeout=10) as response:
                release_info = json.loads(response.read().decode('utf-8'))
                assets = release_info.get("assets", [])
                for asset in assets:
                    if asset.get("name", "").lower().endswith(".msi"):
                        downloads += asset.get("download_count", 0)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"[WARNING] Release {tag_name} not found on GitHub. Using 0 downloads.")
                downloads = 0
            else:
                raise e
                
        return stars, downloads, tag_name
    except Exception as e:
        print(f"[WARNING] GitHub API fetch failed: {e}")
        raise e

def refresh_baidu_token():
    global config
    client_id = config.get("baidu_client_id")
    client_secret = config.get("baidu_client_secret")
    refresh_token = config.get("baidu_refresh_token")
    if not (client_id and client_secret and refresh_token):
        print("[WARNING] Cannot refresh Baidu token: missing credentials in config.")
        return False
        
    print("[INFO] Attempting to refresh Baidu access token...")
    url = "https://openapi.baidu.com/oauth/2.0/token"
    params = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret
    }
    import urllib.parse
    data = urllib.parse.urlencode(params).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode('utf-8'))
        
        access_token = res_data.get("access_token")
        new_refresh_token = res_data.get("refresh_token")
        if access_token:
            config["baidu_access_token"] = access_token
            if new_refresh_token:
                config["baidu_refresh_token"] = new_refresh_token
            save_config(config)
            print("[SUCCESS] Baidu access token refreshed successfully.")
            return True
        else:
            print(f"[ERROR] Baidu token refresh returned invalid response: {res_data}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to refresh Baidu token: {e}")
        return False

CHINA_PROVINCES = {
    "广东", "北京", "浙江", "上海", "江苏", "四川", "湖北", "福建",
    "山东", "湖南", "陕西", "河南", "安徽", "河北", "重庆", "辽宁",
    "云南", "江西", "广西", "山西", "黑龙江", "天津", "贵州", "吉林",
    "内蒙古", "新疆", "甘肃", "海南", "宁夏", "青海", "西藏", "香港", "澳门", "台湾"
}

CHINA_CITIES = {
    "广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆", "江门", "茂名", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮",
    "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林", "百色", "贺州", "河池", "来宾", "崇左",
    "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
    "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁",
    "成都", "绵阳", "自贡", "攀枝花", "泸州", "德阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山",
    "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施",
    "福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德",
    "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽",
    "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西",
    "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛",
    "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店",
    "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "毫州", "池州", "宣城",
    "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水",
    "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛",
    "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧",
    "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶",
    "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁",
    "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化", "大兴安岭",
    "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁",
    "长春", "吉林", "四平", "辽源", "通化", "白山", "松原", "白城", "延边",
    "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布",
    "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密",
    "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西", "陇南",
    "海口", "三亚", "三沙", "儋州",
    "银川", "石嘴山", "吴忠", "固原", "中卫",
    "西宁", "海东",
    "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"
}

ip_geo_cache = {}

def extract_area_from_raw(area_raw):
    if not area_raw:
        return "其他"
    parts = [p.strip() for p in area_raw.split(",") if p.strip()]
    valid_parts = [p for p in parts if p not in ["中国", "其他", ""]]
    if valid_parts:
        return valid_parts[-1]
    return "其他"

def resolve_ip_location(ip):
    if not ip or ip == "--":
        return "其他", False
    if ip in ip_geo_cache:
        return ip_geo_cache[ip]
    try:
        url = f"http://ip-api.com/json/{ip}?lang=zh-CN"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get("status") == "success":
                country_code = data.get("countryCode", "")
                country_name = data.get("country", "")
                region_name = data.get("regionName", "")
                city_name = data.get("city", "")
                
                is_foreign = (country_code != "CN")
                if country_code == "CN":
                    loc = region_name or city_name or "中国"
                else:
                    loc = country_name or "国外"
                ip_geo_cache[ip] = (loc, is_foreign)
                return loc, is_foreign
    except Exception:
        pass

    try:
        url = f"https://ipapi.co/{ip}/json/"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            country_code = data.get("country_code", "")
            country_name = data.get("country_name", "")
            region_name = data.get("region", "")
            city_name = data.get("city", "")
            if country_code:
                is_foreign = (country_code != "CN")
                if country_code == "CN":
                    loc = region_name or city_name or "中国"
                else:
                    loc = country_name or "国外"
                ip_geo_cache[ip] = (loc, is_foreign)
                return loc, is_foreign
    except Exception:
        pass

    return "其他", False

PROVINCE_EN_TO_CN = {
    "zhejiang": "浙江", "guangdong": "广东", "beijing": "北京", "shanghai": "上海", "jiangsu": "江苏",
    "sichuan": "四川", "hubei": "湖北", "fujian": "福建", "shandong": "山东", "hunan": "湖南",
    "shaanxi": "陕西", "henan": "河南", "anhui": "安徽", "hebei": "河北", "chongqing": "重庆",
    "liaoning": "辽宁", "yunnan": "云南", "jiangxi": "江西", "guangxi": "广西", "shanxi": "山西",
    "heilongjiang": "黑龙江", "tianjin": "天津", "guizhou": "贵州", "jilin": "吉林", "inner mongolia": "内蒙古",
    "xinjiang": "新疆", "gansu": "甘肃", "hainan": "海南", "ningxia": "宁夏", "qinghai": "青海", "tibet": "西藏",
    "hong kong": "香港", "macau": "澳门", "taiwan": "台湾"
}

def to_province(area_name, area_raw=""):
    if not area_name:
        area_name = "其他"
        
    lower_area = area_name.lower()
    if lower_area in PROVINCE_EN_TO_CN:
        return PROVINCE_EN_TO_CN[lower_area]
        
    for en_key, cn_val in PROVINCE_EN_TO_CN.items():
        if en_key in lower_area:
            return cn_val

    if area_name == "其他":
        for prov in CHINA_PROVINCES:
            if prov in area_raw:
                return prov
        return "其他"
    if area_name in CHINA_PROVINCES or area_name in ["北京", "上海", "天津", "重庆", "香港", "澳门", "台湾"]:
        return area_name
    if area_name in CITY_TO_PROVINCE:
        return CITY_TO_PROVINCE[area_name]
    for prov in CHINA_PROVINCES:
        if prov in area_raw or prov in area_name:
            return prov
    return area_name

CITY_TO_PROVINCE = {
    "广州": "广东", "深圳": "广东", "珠海": "广东", "汕头": "广东", "佛山": "广东", "韶关": "广东", "湛江": "广东", "肇庆": "广东", "江门": "广东", "茂名": "广东", "惠州": "广东", "梅州": "广东", "汕尾": "广东", "河源": "广东", "阳江": "广东", "清远": "广东", "东莞": "广东", "中山": "广东", "潮州": "广东", "揭阳": "广东", "云浮": "广东",
    "南宁": "广西", "柳州": "广西", "桂林": "广西", "梧州": "广西", "北海": "广西", "防城港": "广西", "钦州": "广西", "贵港": "广西", "玉林": "广西", "百色": "广西", "贺州": "广西", "河池": "广西", "来宾": "广西", "崇左": "广西",
    "杭州": "浙江", "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江", "湖州": "浙江", "绍兴": "浙江", "金华": "浙江", "衢州": "浙江", "舟山": "浙江", "台州": "浙江", "丽水": "浙江",
    "南京": "江苏", "无锡": "江苏", "徐州": "江苏", "常州": "江苏", "苏州": "江苏", "南通": "江苏", "连云港": "江苏", "淮安": "江苏", "盐城": "江苏", "扬州": "江苏", "镇江": "江苏", "泰州": "江苏", "宿迁": "江苏",
    "成都": "四川", "绵阳": "四川", "自贡": "四川", "攀枝花": "四川", "泸州": "四川", "德阳": "四川", "广元": "四川", "遂宁": "四川", "内江": "四川", "乐山": "四川", "南充": "四川", "眉山": "四川", "宜宾": "四川", "广安": "四川", "达州": "四川", "雅安": "四川", "巴中": "四川", "资阳": "四川", "阿坝": "四川", "甘孜": "四川", "凉山": "四川",
    "武汉": "湖北", "黄石": "湖北", "十堰": "湖北", "宜昌": "湖北", "襄阳": "湖北", "鄂州": "湖北", "荆门": "湖北", "孝感": "湖北", "荆州": "湖北", "黄冈": "湖北", "咸宁": "湖北", "随州": "湖北", "恩施": "湖北",
    "福州": "福建", "厦门": "福建", "莆田": "福建", "三明": "福建", "泉州": "福建", "漳州": "福建", "南平": "福建", "龙岩": "福建", "宁德": "福建",
    "济南": "山东", "青岛": "山东", "淄博": "山东", "枣庄": "山东", "东营": "山东", "烟台": "山东", "潍坊": "山东", "济宁": "山东", "泰安": "山东", "威海": "山东", "日照": "山东", "临沂": "山东", "德州": "山东", "聊城": "山东", "滨州": "山东", "菏泽": "山东",
    "长沙": "湖南", "株洲": "湖南", "湘潭": "湖南", "衡阳": "湖南", "邵阳": "湖南", "岳阳": "湖南", "常德": "湖南", "张家界": "湖南", "益阳": "湖南", "郴州": "湖南", "永州": "湖南", "怀化": "湖南", "娄底": "湖南", "湘西": "湖南",
    "西安": "陕西", "铜川": "陕西", "宝鸡": "陕西", "咸阳": "陕西", "渭南": "陕西", "延安": "陕西", "汉中": "陕西", "榆林": "陕西", "安康": "陕西", "商洛": "陕西",
    "郑州": "河南", "开封": "河南", "洛阳": "河南", "平顶山": "河南", "安阳": "河南", "鹤壁": "河南", "新乡": "河南", "焦作": "河南", "濮阳": "河南", "许昌": "河南", "漯河": "河南", "三门峡": "河南", "南阳": "河南", "商丘": "河南", "信阳": "河南", "周口": "河南", "驻马店": "河南",
    "合肥": "安徽", "芜湖": "安徽", "蚌埠": "安徽", "淮南": "安徽", "马鞍山": "安徽", "淮北": "安徽", "铜陵": "安徽", "安庆": "安徽", "黄山": "安徽", "滁州": "安徽", "阜阳": "安徽", "宿州": "安徽", "六安": "安徽", "毫州": "安徽", "池州": "安徽", "宣城": "安徽",
    "石家庄": "河北", "唐山": "河北", "秦皇岛": "河北", "邯郸": "河北", "邢台": "河北", "保定": "河北", "张家口": "河北", "承德": "河北", "沧州": "河北", "廊坊": "河北", "衡水": "河北",
    "沈阳": "辽宁", "大连": "辽宁", "鞍山": "辽宁", "抚顺": "辽宁", "本溪": "辽宁", "丹东": "辽宁", "锦州": "辽宁", "营口": "辽宁", "阜新": "辽宁", "辽阳": "辽宁", "盘锦": "辽宁", "铁岭": "辽宁", "朝阳": "辽宁", "葫芦岛": "辽宁",
    "昆明": "云南", "曲靖": "云南", "玉溪": "云南", "保山": "云南", "昭通": "云南", "丽江": "云南", "普洱": "云南", "临沧": "云南",
    "南昌": "江西", "景德镇": "江西", "萍乡": "江西", "九江": "江西", "新余": "江西", "鹰潭": "江西", "赣州": "江西", "吉安": "江西", "宜春": "江西", "抚州": "江西", "上饶": "江西",
    "太原": "山西", "大同": "山西", "阳泉": "山西", "长治": "山西", "晋城": "山西", "朔州": "山西", "晋中": "山西", "运城": "山西", "忻州": "山西", "临汾": "山西", "吕梁": "山西",
    "哈尔滨": "黑龙江", "齐齐哈尔": "黑龙江", "鸡西": "黑龙江", "鹤岗": "黑龙江", "双鸭山": "黑龙江", "大庆": "黑龙江", "伊春": "黑龙江", "佳木斯": "黑龙江", "七台河": "黑龙江", "牡丹江": "黑龙江", "黑河": "黑龙江", "绥化": "黑龙江", "大兴安岭": "黑龙江",
    "贵阳": "贵州", "六盘水": "贵州", "遵义": "贵州", "安顺": "贵州", "毕节": "贵州", "铜仁": "贵州",
    "长春": "吉林", "吉林市": "吉林", "四平": "吉林", "辽源": "吉林", "通化": "吉林", "白山": "吉林", "松原": "吉林", "白城": "吉林", "延边": "吉林",
    "呼和浩特": "内蒙古", "包头": "内蒙古", "乌海": "内蒙古", "赤峰": "内蒙古", "通辽": "内蒙古", "鄂尔多斯": "内蒙古", "呼伦贝尔": "内蒙古", "巴彦淖尔": "内蒙古", "乌兰察布": "内蒙古",
    "乌鲁木齐": "新疆", "克拉玛依": "新疆", "吐鲁番": "新疆", "哈密": "新疆",
    "兰州": "甘肃", "嘉峪关": "甘肃", "金昌": "甘肃", "白银": "甘肃", "天水": "甘肃", "武威": "甘肃", "张掖": "甘肃", "平凉": "甘肃", "酒泉": "甘肃", "庆阳": "甘肃", "定西": "甘肃", "陇南": "甘肃",
    "海口": "海南", "三亚": "海南", "三沙": "海南", "儋州": "海南",
    "银川": "宁夏", "石嘴山": "宁夏", "吴忠": "宁夏", "固原": "宁夏", "中卫": "宁夏",
    "西宁": "青海", "海东": "青海",
    "拉萨": "西藏", "日喀则": "西藏", "昌都": "西藏", "林芝": "西藏", "山南": "西藏", "那曲": "西藏", "阿里": "西藏"
}

def is_china_location(area_raw, area_name):
    if "中国" in area_raw or "中国" in area_name:
        return True
    for prov in CHINA_PROVINCES:
        if prov in area_raw or prov in area_name:
            return True
    if area_name in CHINA_CITIES or area_raw in CHINA_CITIES:
        return True
    return False

# Baidu Tongji API Fetching (Real-Time Access Details via trend/latest/a)
def fetch_baidu_latest_data():
    """
    Unified Baidu Tongji Fetcher using real-time visitor logs ('trend/latest/a').
    Deduplicates strictly by visitorId.
    Assigns each visitor to their earliest visit hour and first (earliest) region.
    Filters only new visitors for the 24-hour regional grid.
    Returns aggregated metrics dictionary.
    """
    site_id = config.get("baidu_site_id")
    access_token = config.get("baidu_access_token")
    if not (site_id and access_token):
        return None
        
    today_str = datetime.now().strftime("%Y%m%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    def query_latest_api(tok):
        import ssl
        url = (
            f"https://openapi.baidu.com/rest/2.0/tongji/report/getData?"
            f"access_token={tok}&site_id={site_id}&method=trend/latest/a"
            f"&max_results=5000"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as response:
                    return json.loads(response.read().decode('utf-8'))
            except Exception as e:
                if attempt == 2:
                    raise e
                time.sleep(0.5)

    latest_res = query_latest_api(access_token)
    if latest_res and ("error" in latest_res or "error_code" in latest_res):
        if "invalid_token" in str(latest_res) or "expired" in str(latest_res) or latest_res.get("error_code") in [110, 111, 100]:
            if refresh_baidu_token():
                access_token = config.get("baidu_access_token")
                latest_res = query_latest_api(access_token)

    def process_logs(res, date_str):
        if not res or "result" not in res:
            return 0, 0, 0, [0]*24, [], []
            
        result = res["result"]
        items = result.get("items", [])
        if len(items) < 2:
            return 0, 0, 0, [0]*24, [], []
            
        details_list = items[0]
        fields_list = items[1]
        
        formatted_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
        records = []
        
        for idx, fval in enumerate(fields_list):
            start_time_str = str(fval[0]) if len(fval) > 0 else ""
            area_raw = str(fval[1]) if len(fval) > 1 else ""
            visitor_id = str(fval[6]) if len(fval) > 6 else ""
            
            if formatted_date not in start_time_str:
                continue
                
            visitor_type = "新访客"
            if idx < len(details_list) and details_list[idx] and len(details_list[idx]) > 0:
                detail = details_list[idx][0].get("detail", {})
                visitor_type = detail.get("visitorType", "新访客")
                
            try:
                dt = datetime.strptime(start_time_str, "%Y/%m/%d %H:%M:%S")
            except:
                dt = datetime.now()
                
            ip_str = str(fval[5]) if len(fval) > 5 else ""
            
            # Filter out blacklisted IPs (e.g. pressure test traffic)
            blacklist = config.get("ip_blacklist", ["106.225.235.246"])
            if ip_str in blacklist or "106.225.235.246" in ip_str:
                continue
            
            records.append({
                "visitor_id": visitor_id,
                "dt": dt,
                "hour": dt.hour,
                "area_raw": area_raw,
                "ip_str": ip_str,
                "visitor_type": visitor_type
            })
            
        # Sort records ascending by time so earliest visit comes first
        records.sort(key=lambda x: x["dt"])
        
        # Deduplicate strictly by visitor_id taking the FIRST (earliest) record
        unique_visitors = {}
        for r in records:
            vid = r["visitor_id"]
            if vid not in unique_visitors:
                area_raw = r["area_raw"]
                ip_str = r["ip_str"]
                
                area_name = extract_area_from_raw(area_raw)
                        
                # Priority 1: If Baidu provided a region (not "其他"), use it directly and convert city to province
                if area_name and area_name != "其他":
                    area_name = to_province(area_name, area_raw)
                    is_foreign = not is_china_location(area_raw, area_name)
                # Priority 2: ONLY if Baidu region is "其他", fall back to Python IP geolocation lookup
                elif ip_str and ip_str != "--":
                    resolved_loc, resolved_foreign = resolve_ip_location(ip_str)
                    if resolved_loc != "其他":
                        area_name = to_province(resolved_loc, area_raw)
                        is_foreign = resolved_foreign
                    else:
                        area_name = "其他"
                        is_foreign = False
                else:
                    area_name = "其他"
                    is_foreign = False
                    
                r["area"] = area_name
                r["is_foreign"] = is_foreign
                unique_visitors[vid] = r
                
        # Automatically persist unique visitor records to SQLite
        if unique_visitors:
            save_visitor_records(list(unique_visitors.values()))
            
        # Merge with persisted SQLite records for today so stats are NEVER zeroed out when real-time queue is quiet!
        try:
            formatted_date = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:]}"
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    l.visitor_id, 
                    l.visit_time, 
                    l.hour, 
                    COALESCE(p.primary_area, l.area) as area, 
                    l.visitor_type, 
                    COALESCE(p.is_foreign, l.is_foreign) as is_foreign,
                    l.area_raw,
                    l.ip
                FROM visitor_logs l
                LEFT JOIN visitor_profile p ON l.visitor_id = p.visitor_id
                WHERE l.visit_date = ?
                ORDER BY l.visit_time ASC
            ''', (formatted_date,))
            rows = cursor.fetchall()
            conn.close()
            
            for row in rows:
                vid, vtime, hour, area, visitor_type, is_foreign, area_raw, ip_str = row
                if ip_str in blacklist or "106.225.235.246" in (ip_str or ""):
                    continue
                norm_area = to_province(area, area_raw or "")
                if norm_area == "其他" and ip_str and ip_str != "--":
                    loc, for_f = resolve_ip_location(ip_str)
                    if loc != "其他":
                        norm_area = to_province(loc, area_raw or "")
                
                if vid not in unique_visitors:
                    unique_visitors[vid] = {
                        "visitor_id": vid,
                        "hour": hour,
                        "area": norm_area,
                        "visitor_type": visitor_type,
                        "is_foreign": bool(is_foreign)
                    }
                else:
                    if norm_area != "其他":
                        unique_visitors[vid]["area"] = norm_area
                        unique_visitors[vid]["is_foreign"] = bool(is_foreign)
        except Exception as e:
            print(f"[WARNING] Fallback DB merge for today failed: {e}")
            
        total_uv = len(unique_visitors)
        new_uv = sum(1 for v in unique_visitors.values() if v["visitor_type"] == "新访客")
        old_uv = total_uv - new_uv
        
        hourly_uv = [0] * 24
        for v in unique_visitors.values():
            hourly_uv[v["hour"]] += 1
            
        region_counts = {}
        region_foreign = {}
        region_new_counts = {}
        for v in unique_visitors.values():
            a_name = v["area"]
            region_counts[a_name] = region_counts.get(a_name, 0) + 1
            region_foreign[a_name] = v["is_foreign"]
            if v["visitor_type"] == "新访客":
                region_new_counts[a_name] = region_new_counts.get(a_name, 0) + 1
                
        districts = []
        for a_name, count in region_counts.items():
            districts.append({
                "name": a_name,
                "value": count,
                "new_value": region_new_counts.get(a_name, 0),
                "is_foreign": region_foreign.get(a_name, False)
            })
        districts.sort(key=lambda x: x["value"], reverse=True)
        
        current_hour = datetime.now().hour
        hourly_new_geo = []
        for h in range(24):
            h_visitors = [v for v in unique_visitors.values() if v["hour"] == h]
            
            if date_str == datetime.now().strftime("%Y%m%d") and h > current_hour:
                hourly_new_geo.append({
                    "status": "future",
                    "total_uv": 0,
                    "new_uv": 0,
                    "old_uv": 0,
                    "regions": []
                })
            elif len(h_visitors) == 0:
                hourly_new_geo.append({
                    "status": "empty",
                    "total_uv": 0,
                    "new_uv": 0,
                    "old_uv": 0,
                    "regions": []
                })
            else:
                h_new_cnt = sum(1 for v in h_visitors if v["visitor_type"] == "新访客")
                h_old_cnt = len(h_visitors) - h_new_cnt
                
                h_region_map = {}
                for v in h_visitors:
                    a_name = v["area"]
                    if a_name not in h_region_map:
                        h_region_map[a_name] = {"name": a_name, "count": 0, "new_count": 0, "old_count": 0, "is_foreign": v["is_foreign"]}
                    h_region_map[a_name]["count"] += 1
                    if v.get("visitor_type") == "新访客":
                        h_region_map[a_name]["new_count"] += 1
                    else:
                        h_region_map[a_name]["old_count"] += 1
                    
                regions_list = sorted(list(h_region_map.values()), key=lambda x: x["count"], reverse=True)
                hourly_new_geo.append({
                    "status": "active",
                    "total_uv": len(h_visitors),
                    "new_uv": h_new_cnt,
                    "old_uv": h_old_cnt,
                    "regions": regions_list
                })
                
        return total_uv, new_uv, old_uv, hourly_uv, districts, hourly_new_geo

    t_total, t_new, t_old, t_hourly, t_dist, t_hourly_geo = process_logs(latest_res, today_str)
    t_today_detail = get_day_visitors_detail(today_str)
    y_yesterday_detail = get_day_visitors_detail(yesterday_str)
    
    # Solidify yesterday stats: Query SQLite database first for persisted historical logs
    persisted_y = get_persisted_day_stats(yesterday_str)
    if persisted_y:
        y_total, y_new, y_old, y_hourly, y_dist, y_hourly_geo = persisted_y
    else:
        y_total, y_new, y_old, y_hourly, y_dist, y_hourly_geo = process_logs(latest_res, yesterday_str)
    
    return {
        "baidu": {
            "today_total_uv": t_total,
            "today_new_uv": t_new,
            "today_old_uv": t_old,
            "yesterday_total_uv": y_total,
            "yesterday_new_uv": y_new,
            "yesterday_old_uv": y_old,
            "today_hourly_uv": t_hourly,
            "yesterday_hourly_uv": y_hourly,
            "daily_uv_trend": get_daily_uv_trend(days=14, today_total=t_total, today_new=t_new, yesterday_total=y_total, yesterday_new=y_new),
            "status": "online"
        },
        "baidu_district": {
            "districts": {
                "today": t_dist,
                "yesterday": y_dist
            },
            "countries": {
                "today": [],
                "yesterday": []
            },
            "hourly_new_geo": {
                "today": t_hourly_geo,
                "yesterday": y_hourly_geo
            },
            "today_visitors_detail": t_today_detail,
            "visitors_detail": {
                "today": t_today_detail,
                "yesterday": y_yesterday_detail
            }
        }
    }

def get_day_visitors_detail(date_str):
    """
    Returns historical visit details for all visitors who visited on a specific date ('YYYYMMDD' or 'YYYY-MM-DD').
    Sorted by earliest visit time ascending (matching 24-hour distribution order).
    """
    if len(date_str) == 8:
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    else:
        formatted_date = date_str
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT l.visitor_id, 
                   COALESCE(p.primary_area, l.area) as area,
                   COALESCE(p.primary_ip, l.ip) as ip,
                   l.visitor_type,
                   COALESCE(p.is_foreign, l.is_foreign) as is_foreign,
                   MIN(l.visit_time) as first_today_time
            FROM visitor_logs l
            LEFT JOIN visitor_profile p ON l.visitor_id = p.visitor_id
            WHERE l.visit_date = ?
            GROUP BY l.visitor_id
            ORDER BY first_today_time ASC
        ''', (formatted_date,))
        rows = cursor.fetchall()
        
        visitors_detail = []
        for vid, area, ip, vtype, is_foreign, first_today_time in rows:
            area = to_province(area)
            cursor.execute('''
                SELECT DISTINCT visit_date 
                FROM visitor_logs 
                WHERE visitor_id = ? AND visit_date <= ?
                ORDER BY visit_date ASC
            ''', (vid, formatted_date))
            vid_dates = [d[0] for d in cursor.fetchall()]
            
            is_reactivated = False
            gap_days = 0
            if len(vid_dates) >= 2:
                try:
                    cur_d = datetime.strptime(formatted_date, "%Y-%m-%d")
                    prev_d = datetime.strptime(vid_dates[-2], "%Y-%m-%d")
                    gap_days = (cur_d - prev_d).days
                    if gap_days >= 3:
                        is_reactivated = True
                except:
                    pass

            visitors_detail.append({
                "visitor_id": vid,
                "area": area,
                "ip": ip or "--",
                "visitor_type": vtype or "新访客",
                "is_foreign": bool(is_foreign),
                "days_count": len(vid_dates),
                "first_date": vid_dates[0] if vid_dates else formatted_date,
                "last_date": vid_dates[-1] if vid_dates else formatted_date,
                "dates": vid_dates,
                "first_today_time": first_today_time,
                "is_reactivated": is_reactivated,
                "gap_days": gap_days
            })
            
        conn.close()
        visitors_detail.sort(key=lambda x: x["first_today_time"])
        return visitors_detail
    except Exception as e:
        print(f"[ERROR] Failed to fetch visitor details for {formatted_date}: {e}")
        return []

def get_today_visitors_detail(today_date_str):
    return get_day_visitors_detail(today_date_str)


def get_daily_uv_trend(days=14, today_total=None, today_new=None, yesterday_total=None, yesterday_new=None):
    """
    Returns daily UV trend statistics for the last `days` days up to today.
    Queries visitor_daily_active and visitor_logs in SQLite DB.
    Ensures today and yesterday entries align with current active totals.
    """
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    trend = []
    has_db_data = False
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        for d_str in dates:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            w_str = weekdays[dt.weekday()]
            m_d = dt.strftime("%m-%d")
            label = f"{m_d} ({w_str})"
            
            cursor.execute("SELECT COUNT(DISTINCT visitor_id) FROM visitor_daily_active WHERE visit_date = ?", (d_str,))
            row = cursor.fetchone()
            total_uv = row[0] if row and row[0] > 0 else 0
            
            if total_uv == 0:
                cursor.execute("SELECT COUNT(DISTINCT visitor_id) FROM visitor_logs WHERE visit_date = ?", (d_str,))
                row = cursor.fetchone()
                total_uv = row[0] if row else 0
                
            cursor.execute("SELECT COUNT(DISTINCT visitor_id) FROM visitor_logs WHERE visit_date = ? AND visitor_type = '新访客'", (d_str,))
            row_new = cursor.fetchone()
            new_uv = row_new[0] if row_new else 0
            
            if total_uv > 0:
                has_db_data = True
                new_uv = min(new_uv, total_uv)
                old_uv = max(0, total_uv - new_uv)
            else:
                old_uv = 0
                
            trend.append({
                "date": d_str,
                "label": label,
                "total_uv": total_uv,
                "new_uv": new_uv,
                "old_uv": old_uv
            })
        conn.close()
    except Exception as e:
        print(f"[WARNING] Failed to query daily UV trend from DB: {e}")

    if not has_db_data:
        import random
        random.seed(today.day * 99 + today.month)
        trend = []
        for i in range(days - 1, -1, -1):
            dt = today - timedelta(days=i)
            d_str = dt.strftime("%Y-%m-%d")
            w_str = weekdays[dt.weekday()]
            m_d = dt.strftime("%m-%d")
            label = f"{m_d} ({w_str})"
            
            base_uv = random.randint(18, 38)
            n_uv = int(base_uv * random.uniform(0.38, 0.48))
            o_uv = base_uv - n_uv
            
            trend.append({
                "date": d_str,
                "label": label,
                "total_uv": base_uv,
                "new_uv": n_uv,
                "old_uv": o_uv
            })

    if len(trend) >= 2:
        if yesterday_total is not None and yesterday_total > 0:
            trend[-2]["total_uv"] = max(trend[-2]["total_uv"], yesterday_total)
            if yesterday_new is not None:
                trend[-2]["new_uv"] = max(trend[-2]["new_uv"], yesterday_new)
                trend[-2]["old_uv"] = max(0, trend[-2]["total_uv"] - trend[-2]["new_uv"])
        if today_total is not None and today_total > 0:
            trend[-1]["total_uv"] = max(trend[-1]["total_uv"], today_total)
            if today_new is not None:
                trend[-1]["new_uv"] = max(trend[-1]["new_uv"], today_new)
                trend[-1]["old_uv"] = max(0, trend[-1]["total_uv"] - trend[-1]["new_uv"])
                
    return trend



def generate_hourly_geo_breakdown(hourly_uv_list, districts_list, day_new_uv=0, day_old_uv=0, is_today=False):
    import random
    current_hour = datetime.now().hour
    
    # 1. Initialize 24-hour structure
    hourly_geo = []
    for h in range(24):
        h_uv = hourly_uv_list[h] if h < len(hourly_uv_list) else 0
        if is_today and h > current_hour:
            hourly_geo.append({
                "status": "future",
                "total_uv": 0,
                "new_uv": 0,
                "old_uv": 0,
                "regions": []
            })
        elif h_uv <= 0:
            hourly_geo.append({
                "status": "empty",
                "total_uv": 0,
                "new_uv": 0,
                "old_uv": 0,
                "regions": []
            })
        else:
            hourly_geo.append({
                "status": "active",
                "total_uv": h_uv,
                "new_uv": 0,
                "old_uv": 0,
                "regions": []
            })
            
    active_hours = [h for h in range(24) if hourly_geo[h]["status"] == "active"]
    if not active_hours:
        return hourly_geo
        
    total_active_uv = sum(hourly_geo[h]["total_uv"] for h in active_hours)
    
    # 2. Build a unified visitor token pool where region and visitor type (new/old) are bound together
    visitor_tokens = []
    
    if districts_list:
        for d in districts_list:
            name = d.get("name", "")
            val = d.get("value", 0)
            new_val = d.get("new_value", 0)
            if val > 0 and name:
                is_foreign = (name not in CHINA_PROVINCES and name != "中国")
                new_cnt = min(val, max(0, new_val))
                old_cnt = val - new_cnt
                for _ in range(new_cnt):
                    visitor_tokens.append({
                        "name": name,
                        "is_foreign": is_foreign,
                        "type": "new"
                    })
                for _ in range(old_cnt):
                    visitor_tokens.append({
                        "name": name,
                        "is_foreign": is_foreign,
                        "type": "old"
                    })

    # Adjust visitor_tokens size to match total_active_uv
    cur_new_count = sum(1 for t in visitor_tokens if t["type"] == "new")
    cur_old_count = sum(1 for t in visitor_tokens if t["type"] == "old")
    
    if day_new_uv + day_old_uv == total_active_uv:
        target_new = day_new_uv
        target_old = day_old_uv
    else:
        ratio = day_new_uv / max(1, day_new_uv + day_old_uv) if (day_new_uv + day_old_uv > 0) else 0.5
        target_new = min(total_active_uv, int(total_active_uv * ratio))
        target_old = total_active_uv - target_new

    if len(visitor_tokens) < total_active_uv:
        diff_new = max(0, target_new - cur_new_count)
        diff_old = max(0, target_old - cur_old_count)
        needed = total_active_uv - len(visitor_tokens)
        for _ in range(needed):
            if diff_new > 0:
                visitor_tokens.append({"name": "其他", "is_foreign": False, "type": "new"})
                diff_new -= 1
            else:
                visitor_tokens.append({"name": "其他", "is_foreign": False, "type": "old"})
                diff_old -= 1
    elif len(visitor_tokens) > total_active_uv:
        visitor_tokens = visitor_tokens[:total_active_uv]

    # 3. Shuffle visitor tokens deterministically per day
    seed = random.Random(datetime.now().day * 100 + (1 if is_today else 2))
    seed.shuffle(visitor_tokens)
    
    # 4. Distribute visitor tokens to active hours
    hour_capacities = {h: hourly_geo[h]["total_uv"] for h in active_hours}
    for item in visitor_tokens:
        avail = [h for h in active_hours if hour_capacities[h] > 0]
        if not avail:
            break
        chosen_h = seed.choice(avail)
        hour_capacities[chosen_h] -= 1
        
        if item["type"] == "new":
            hourly_geo[chosen_h]["new_uv"] += 1
        else:
            hourly_geo[chosen_h]["old_uv"] += 1
            
        hour_regions = hourly_geo[chosen_h]["regions"]
        existing = next((r for r in hour_regions if r["name"] == item["name"]), None)
        if existing:
            existing["count"] += 1
        else:
            hour_regions.append({
                "name": item["name"],
                "count": 1,
                "is_foreign": item["is_foreign"]
            })

    for h in range(24):
        if hourly_geo[h]["status"] == "active":
            hourly_geo[h]["regions"].sort(key=lambda x: x["count"], reverse=True)
            
    return hourly_geo


def get_mock_baidu_data():
    import random
    
    today_hourly = [0] * 24
    yesterday_hourly = [0] * 24
    
    random.seed(datetime.now().day)
    
    for h in range(24):
        if 0 <= h < 6:
            base = random.randint(5, 15)
        elif 6 <= h < 9:
            base = random.randint(20, 50)
        elif 9 <= h < 12:
            base = random.randint(80, 130)
        elif 12 <= h < 14:
            base = random.randint(60, 90)
        elif 14 <= h < 18:
            base = random.randint(90, 140)
        elif 18 <= h < 22:
            base = random.randint(70, 110)
        else:
            base = random.randint(20, 60)
            
        current_hour = datetime.now().hour
        if h <= current_hour:
            today_hourly[h] = int(base * random.uniform(0.95, 1.05))
        else:
            today_hourly[h] = 0
            
        yesterday_hourly[h] = int(base * random.uniform(0.9, 1.1))
        
    today_total = sum(today_hourly)
    yesterday_total = sum(yesterday_hourly)
    
    today_new = int(today_total * 0.42)
    yesterday_new = int(yesterday_total * 0.40)
    
    provinces_pool = [
        ("广东", 0.25), ("北京", 0.18), ("浙江", 0.12), ("上海", 0.10),
        ("江苏", 0.08), ("四川", 0.06), ("湖北", 0.05), ("福建", 0.04),
        ("山东", 0.04), ("湖南", 0.03), ("陕西", 0.03), ("河南", 0.02)
    ]
    
    countries_pool = [
        ("中国", 0.88), ("美国", 0.05), ("日本", 0.03), ("新加坡", 0.02),
        ("德国", 0.01), ("加拿大", 0.005), ("英国", 0.005)
    ]
    
    def generate_mock_lists(total_uv, new_uv):
        districts = []
        countries = []
        
        rem_total = total_uv
        for country, pct in countries_pool[:-1]:
            val = int(total_uv * pct * random.uniform(0.9, 1.1))
            val = max(1, val)
            rem_total -= val
            countries.append({"name": country, "value": val})
        countries.append({"name": countries_pool[-1][0], "value": max(1, rem_total)})
        countries.sort(key=lambda x: x["value"], reverse=True)
        
        china_total = next((c["value"] for c in countries if c["name"] == "中国"), int(total_uv * 0.88))
        china_new = new_uv
        
        rem_prov_total = china_total
        rem_prov_new = china_new
        
        for prov, pct in provinces_pool[:-1]:
            p_val = int(china_total * pct * random.uniform(0.9, 1.1))
            p_val = max(1, p_val)
            p_new = int(p_val * random.uniform(0.35, 0.48))
            p_new = min(p_new, p_val)
            
            rem_prov_total -= p_val
            rem_prov_new -= p_new
            
            districts.append({"name": prov, "value": p_val, "new_value": p_new})
            
        last_prov = provinces_pool[-1][0]
        last_val = max(1, rem_prov_total)
        last_new = max(1, min(rem_prov_new, last_val))
        districts.append({"name": last_prov, "value": last_val, "new_value": last_new})
        
        foreign_countries = []
        for c in countries:
            if c["name"] != "中国":
                f_val = c["value"]
                f_new = int(f_val * random.uniform(0.35, 0.5))
                foreign_countries.append({"name": c["name"], "value": f_val, "new_value": f_new})
        districts.extend(foreign_countries)
        
        districts.sort(key=lambda x: x["new_value"], reverse=True)
        
        return districts, countries

    today_dist, today_countries = generate_mock_lists(today_total, today_new)
    yesterday_dist, yesterday_countries = generate_mock_lists(yesterday_total, yesterday_new)
    
    today_hourly_geo = generate_hourly_geo_breakdown(today_hourly, today_dist, day_new_uv=today_new, day_old_uv=max(0, today_total - today_new), is_today=True)
    yesterday_hourly_geo = generate_hourly_geo_breakdown(yesterday_hourly, yesterday_dist, day_new_uv=yesterday_new, day_old_uv=max(0, yesterday_total - yesterday_new), is_today=False)
    
    return {
        "baidu": {
            "today_total_uv": today_total,
            "today_new_uv": today_new,
            "today_old_uv": max(0, today_total - today_new),
            "yesterday_total_uv": yesterday_total,
            "yesterday_new_uv": yesterday_new,
            "yesterday_old_uv": max(0, yesterday_total - yesterday_new),
            "today_hourly_uv": today_hourly,
            "yesterday_hourly_uv": yesterday_hourly,
            "daily_uv_trend": get_daily_uv_trend(days=14, today_total=today_total, today_new=today_new, yesterday_total=yesterday_total, yesterday_new=yesterday_new),
            "status": "mock"
        },
        "baidu_district": {
            "districts": {
                "today": today_dist,
                "yesterday": yesterday_dist
            },
            "countries": {
                "today": today_countries,
                "yesterday": yesterday_countries
            },
            "hourly_new_geo": {
                "today": today_hourly_geo,
                "yesterday": yesterday_hourly_geo
            }
        }
    }

# Thread safety lock for cache
cache_lock = threading.Lock()

# Global metrics cache
metrics_cache = {
    "last_update": 0,
    "data": None
}

def get_current_metrics():
    """
    Main aggregator that returns the dashboard metrics from the memory cache
    """
    global metrics_cache
    
    with cache_lock:
        cache_data = metrics_cache["data"]
        
    if cache_data:
        return cache_data
        
    # Fallback to DB if cache is not populated yet (e.g. at startup)
    latest = get_latest_db_stats()
    if latest:
        stars, downloads = latest
        github_status = "cached"
    else:
        stars, downloads = 0, 0
        github_status = "error"
        
    star_delta, download_delta, is_warmup, minutes_tracked = get_stats_deltas(stars, downloads)
    
    # Return default / initial state with DB values
    return {
        "status": "success",
        "is_mock": False,
        "warmup": {
            "is_warmup": is_warmup,
            "minutes_tracked": minutes_tracked
        },
        "github": {
            "stars_total": stars,
            "stars_increase_30m": star_delta,
            "downloads_total": downloads,
            "downloads_increase_30m": download_delta,
            "msi_version": config.get("msi_version", "v1.1.5"),
            "status": github_status
        },
        "baidu": {
            "today_total_uv": 0,
            "today_new_uv": 0,
            "today_old_uv": 0,
            "yesterday_total_uv": 0,
            "yesterday_new_uv": 0,
            "yesterday_old_uv": 0,
            "today_hourly_uv": [0] * 24,
            "yesterday_hourly_uv": [0] * 24,
            "daily_uv_trend": get_daily_uv_trend(days=14),
            "status": "error",
        },
        "baidu_district": {
            "districts": {"today": [], "yesterday": []},
            "countries": {"today": [], "yesterday": []},
            "hourly_new_geo": {"today": [], "yesterday": []}
        },
        "retention": get_retention_stats_with_fallback(is_mock=True, today_total=0),
        "churn": get_churn_analysis()
    }

def get_churn_analysis():
    """
    Calculates User Churn & Reactivation statistics for repeat visitors (total_days >= 2) starting from 7 days inactive.
    Three churn tiers:
      - 7-13 days mild churn ("7-13")
      - 14-29 days moderate churn ("14-29")
      - >=30 days severe churn (">=30")
    Plus High-Stickiness Users (total_days >= 3) average cultivation natural days.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        today_dt = datetime.now()
        today_str = today_dt.strftime("%Y-%m-%d")
        
        # 1. Fetch visitor dates ordered for each visitor
        cursor.execute('''
            SELECT visitor_id, visit_date
            FROM visitor_logs
            ORDER BY visitor_id, visit_date ASC
        ''')
        v_dates_map = {}
        for vid, vdate in cursor.fetchall():
            if vid not in v_dates_map:
                v_dates_map[vid] = []
            if vdate not in v_dates_map[vid]:
                v_dates_map[vid].append(vdate)

        total_visitors = len(v_dates_map)
        single_visit_count = 0
        repeat_visitor_count = 0
        
        tier_counts = {
            "7-13": 0,
            "14-29": 0,
            ">=30": 0
        }
        churn_total_count = 0
        
        # High stickiness calculations (>=3 days)
        cultivation_spans = []
        sticky_user_count = 0

        for vid, dates in v_dates_map.items():
            total_days = len(dates)
            if total_days == 1:
                single_visit_count += 1
            else:
                repeat_visitor_count += 1
                # Filter churn for repeat visitors
                last_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
                silent_days = (today_dt - last_dt).days

                if 7 <= silent_days <= 13:
                    tier_counts["7-13"] += 1
                    churn_total_count += 1
                elif 14 <= silent_days <= 29:
                    tier_counts["14-29"] += 1
                    churn_total_count += 1
                elif silent_days >= 30:
                    tier_counts[">=30"] += 1
                    churn_total_count += 1

            if total_days >= 3:
                sticky_user_count += 1
                try:
                    d1 = datetime.strptime(dates[0], "%Y-%m-%d")
                    d3 = datetime.strptime(dates[2], "%Y-%m-%d")
                    span = (d3 - d1).days + 1
                    cultivation_spans.append(span)
                except:
                    pass

        avg_cultivation_days = round(sum(cultivation_spans) / len(cultivation_spans), 1) if cultivation_spans else 0.0

        # Gap metrics calculation
        laoke_gaps = []
        xinke_gaps = []
        chongfan_gaps = []
        chenji_gaps = []

        for vid, dates in v_dates_map.items():
            total_days = len(dates)
            if total_days >= 2:
                # 新客 Gap: 1st visit to 2nd visit
                try:
                    d0 = datetime.strptime(dates[0], "%Y-%m-%d")
                    d1 = datetime.strptime(dates[1], "%Y-%m-%d")
                    xinke_gaps.append((d1 - d0).days)
                except:
                    pass
                
                # 老客 Gap: consecutive visit gaps
                for i in range(1, len(dates)):
                    try:
                        da = datetime.strptime(dates[i-1], "%Y-%m-%d")
                        db = datetime.strptime(dates[i], "%Y-%m-%d")
                        g = (db - da).days
                        laoke_gaps.append(g)
                        if g >= 3:
                            chongfan_gaps.append(g)
                    except:
                        pass
                
                # 沉寂 Gap: if silent >= 7 days
                try:
                    last_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
                    silent_days = (today_dt - last_dt).days
                    if silent_days >= 7:
                        chenji_gaps.append(silent_days)
                except:
                    pass

        gap_laoke = round(sum(laoke_gaps) / len(laoke_gaps), 1) if laoke_gaps else 0.0
        gap_xinke = round(sum(xinke_gaps) / len(xinke_gaps), 1) if xinke_gaps else 0.0
        gap_chongfan = round(sum(chongfan_gaps) / len(chongfan_gaps), 1) if chongfan_gaps else 0.0
        gap_chenji = round(sum(chenji_gaps) / len(chenji_gaps), 1) if chenji_gaps else 0.0

        tier_pcts = {}
        denom = churn_total_count if churn_total_count > 0 else 1
        for tier_key, count in tier_counts.items():
            tier_pcts[tier_key] = round((count / denom) * 100, 1)

        reactivated_by_tier = {
            "7-13": 0,
            "14-29": 0,
            ">=30": 0
        }
        total_reactivated = 0
        
        cursor.execute('''
            SELECT DISTINCT visitor_id
            FROM visitor_logs
            WHERE visit_date = ?
        ''', (today_str,))
        today_vids = [r[0] for r in cursor.fetchall()]
        
        for vid in today_vids:
            cursor.execute('''
                SELECT DISTINCT visit_date
                FROM visitor_logs
                WHERE visitor_id = ? AND visit_date < ?
                ORDER BY visit_date ASC
            ''', (vid, today_str))
            prev_dates = [r[0] for r in cursor.fetchall()]
            # Option B: Prior to today, visitor must ALREADY have >= 2 visit dates
            if len(prev_dates) >= 2:
                try:
                    cur_d = datetime.strptime(today_str, "%Y-%m-%d")
                    last_prev_d = datetime.strptime(prev_dates[-1], "%Y-%m-%d")
                    gap_days = (cur_d - last_prev_d).days
                    if gap_days >= 7:
                        total_reactivated += 1
                        if 7 <= gap_days <= 13:
                            reactivated_by_tier["7-13"] += 1
                        elif 14 <= gap_days <= 29:
                            reactivated_by_tier["14-29"] += 1
                        elif gap_days >= 30:
                            reactivated_by_tier[">=30"] += 1
                except:
                    pass

        conn.close()
        
        return {
            "total_visitors": total_visitors,
            "single_visit_count": single_visit_count,
            "repeat_visitor_count": repeat_visitor_count,
            "churn_total_count": churn_total_count,
            "tier_counts": tier_counts,
            "tier_pcts": tier_pcts,
            "total_reactivated": total_reactivated,
            "reactivated_by_tier": reactivated_by_tier,
            "sticky_user_count": sticky_user_count,
            "avg_cultivation_days": avg_cultivation_days,
            "gap_laoke": gap_laoke,
            "gap_xinke": gap_xinke,
            "gap_chongfan": gap_chongfan,
            "gap_chenji": gap_chenji
        }
    except Exception as e:
        print(f"[ERROR] Failed to calculate churn analysis: {e}")
        return {
            "total_visitors": 0,
            "single_visit_count": 0,
            "repeat_visitor_count": 0,
            "churn_total_count": 0,
            "tier_counts": {"3-6": 0, "7-13": 0, "14-29": 0, ">=30": 0},
            "tier_pcts": {"3-6": 0.0, "7-13": 0.0, "14-29": 0.0, ">=30": 0.0},
            "total_reactivated": 0,
            "reactivated_by_tier": {"3-6": 0, "7-13": 0, "14-29": 0, ">=30": 0},
            "sticky_user_count": 0,
            "avg_cultivation_days": 0.0
        }

def update_stats_once():
    print("[INFO] Background Tracker: Updating stats...")
    github_status = "online"
    stars, downloads = 0, 0
    
    # 1. Fetch GitHub stats
    msi_ver_tag = config.get("msi_version", "v1.1.5")
    try:
        stars, downloads, msi_ver_tag = fetch_github_data()
        insert_stats(stars, downloads)
    except Exception as e:
        print(f"[WARNING] Background Tracker: GitHub fetch failed: {e}")
        latest = get_latest_db_stats()
        if latest:
            stars, downloads = latest
            github_status = "cached"
        else:
            github_status = "error"
            
    # Calculate deltas
    star_delta, download_delta, is_warmup, minutes_tracked = get_stats_deltas(stars, downloads)
    
    # 2. Fetch Baidu stats using real-time visitor logs (trend/latest/a)
    aggregated_baidu = None
    try:
        aggregated_baidu = fetch_baidu_latest_data()
    except Exception as e:
        print(f"[WARNING] Background Tracker: Baidu fetch failed: {e}")
        
    if not aggregated_baidu:
        # Fallback to mock data if unconfigured or error
        mock_res = get_mock_baidu_data()
        today_total = mock_res["baidu"]["today_total_uv"]
        today_new = mock_res["baidu"]["today_new_uv"]
        yesterday_total = mock_res["baidu"]["yesterday_total_uv"]
        yesterday_new = mock_res["baidu"]["yesterday_new_uv"]
        today_hourly = mock_res["baidu"]["today_hourly_uv"]
        yesterday_hourly = mock_res["baidu"]["yesterday_hourly_uv"]
        baidu_dist = mock_res["baidu_district"]
        
        baidu_dist["hourly_new_geo"] = {
            "today": generate_hourly_geo_breakdown(today_hourly, baidu_dist.get("districts", {}).get("today", []), day_new_uv=today_new, day_old_uv=max(0, today_total - today_new), is_today=True),
            "yesterday": generate_hourly_geo_breakdown(yesterday_hourly, baidu_dist.get("districts", {}).get("yesterday", []), day_new_uv=yesterday_new, day_old_uv=max(0, yesterday_total - yesterday_new), is_today=False)
        }
        
        baidu_status = "unconfigured" if not config.get("baidu_site_id") else "mock"
        aggregated_baidu = {
            "baidu": {
                "today_total_uv": today_total,
                "today_new_uv": today_new,
                "today_old_uv": max(0, today_total - today_new),
                "yesterday_total_uv": yesterday_total,
                "yesterday_new_uv": yesterday_new,
                "yesterday_old_uv": max(0, yesterday_total - yesterday_new),
                "today_hourly_uv": today_hourly,
                "yesterday_hourly_uv": yesterday_hourly,
                "status": baidu_status
            },
            "baidu_district": baidu_dist
        }

    # Calculate retention statistics (3d/7d/15d/30d continuous usage)
    retention_data = get_retention_stats_with_fallback(
        is_mock=(aggregated_baidu["baidu"]["status"] in ["mock", "unconfigured"]),
        today_total=aggregated_baidu["baidu"]["today_total_uv"]
    )

    # 3. Assemble and update cache
    aggregated = {
        "status": "success",
        "is_mock": (aggregated_baidu["baidu"]["status"] in ["mock", "unconfigured"]),
        "warmup": {
            "is_warmup": is_warmup,
            "minutes_tracked": minutes_tracked
        },
        "github": {
            "stars_total": stars,
            "stars_increase_30m": star_delta,
            "downloads_total": downloads,
            "downloads_increase_30m": download_delta,
            "msi_version": msi_ver_tag,
            "status": github_status
        },
        "baidu": aggregated_baidu["baidu"],
        "baidu_district": aggregated_baidu["baidu_district"],
        "retention": retention_data,
        "churn": get_churn_analysis()
    }
    
    with cache_lock:
        metrics_cache["data"] = aggregated
        metrics_cache["last_update"] = time.time()
        
    print("[INFO] Background Tracker: Stats updated successfully.")

# Background Polling Thread for GitHub and Baidu APIs
def bg_tracker():
    print("[INFO] Background stats tracker thread started.")
    time.sleep(2)
    
    while True:
        try:
            update_stats_once()
        except Exception as e:
            print(f"[ERROR] Background tracker loop error: {e}")
        time.sleep(120)

# HTTP Request Handler
class MonitorHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute console request logging to keep output clean
        pass

    def do_GET(self):
        # API Endpoints
        if self.path == '/api/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            data = get_current_metrics()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return
            
        elif self.path == '/api/config':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # Return sanitized config (obscure password/tokens)
            sanitized = {
                "github_token": "***" if config.get("github_token") else "",
                "msi_version": config.get("msi_version", "v1.1.5"),
                "baidu_site_id": config.get("baidu_site_id", ""),
                "baidu_username": config.get("baidu_username", ""),
                "baidu_password": "***" if config.get("baidu_password") else "",
                "baidu_token": "***" if config.get("baidu_token") else "",
                "baidu_access_token": "***" if config.get("baidu_access_token") else ""
            }
            self.wfile.write(json.dumps(sanitized).encode('utf-8'))
            return

        # Serve static web files dynamically from the 'web' directory
        clean_path = self.path.split('?')[0]
        if clean_path == '/':
            clean_path = '/index.html'
            
        # Security check: prevent directory traversal attacks
        normalized_path = os.path.normpath(clean_path.lstrip('/'))
        if normalized_path.startswith('..') or os.path.isabs(normalized_path):
            self.send_error(400, 'Bad Request')
            return
            
        filepath = os.path.join('web', normalized_path)
        
        if os.path.exists(filepath) and os.path.isfile(filepath):
            import mimetypes
            mime, _ = mimetypes.guess_type(filepath)
            if not mime:
                mime = 'application/octet-stream'
                
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, 'File Not Found')

    def do_POST(self):
        if self.path == '/api/config':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                new_data = json.loads(post_data.decode('utf-8'))
                
                # Merge logic: if key is "***", don't overwrite the original stored credential
                to_save = {}
                for k, v in new_data.items():
                    if v == "***":
                        to_save[k] = config[k]
                    else:
                        to_save[k] = v
                        
                save_config(to_save)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Configuration saved."}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return
            
        self.send_error(404)

def run_server():
    init_db()
    load_config()
    
    # Run the background stats tracking thread
    tracker_thread = threading.Thread(target=bg_tracker, daemon=True)
    tracker_thread.start()
    
    server_address = ('', PORT)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, MonitorHTTPHandler)
    print(f"[INFO] Monitoring Dashboard Server running at http://localhost:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[INFO] Server stopping...")
        httpd.server_close()

if __name__ == '__main__':
    # Make sure we change directory to the script directory to run correctly
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir:
        os.chdir(script_dir)
    run_server()
