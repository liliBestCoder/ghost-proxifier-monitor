import ssl
import os
import sys
import json
import sqlite3
import urllib.request
import urllib.error
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

# Reconfigure stdout to use UTF-8 to prevent GBK encoding errors in Windows terminal
sys.stdout.reconfigure(encoding='utf-8')

PORT = int(os.environ.get("PORT", 7000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'monitor.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# Default configurations
DEFAULT_CONFIG = {
    "github_token": "",
    "msi_version": "v1.1.5",
    "posthog": {
        "api_host": "https://us.i.posthog.com",
        "project_api_key": "phc_nF89Du7x954MRygk3pGNsnJ3GUdTZGeTKXXdnmJmwi9M",
        "personal_api_key": "phx_SCPceWtmJ6Es8gEy5gsjS4CiYUN8cQ5VGZL32QbhLUVKngiJ",
        "project_id": "593531"
    },
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
        cursor.execute("DELETE FROM visitor_profile WHERE first_seen_at LIKE '2027%'")
        cursor.execute("DELETE FROM visitor_logs WHERE visit_date LIKE '2027%'")
        cursor.execute("UPDATE visitor_daily_active SET visit_date = substr(visit_date, 1, 10) WHERE length(visit_date) > 10")
        cursor.execute("DELETE FROM visitor_daily_active WHERE visit_date LIKE '2027%' OR length(visit_date) != 10")
        
        # Re-resolve visitor_logs with real_ip
        cursor.execute("SELECT id, area, area_raw, ip, is_foreign FROM visitor_logs")
        logs = cursor.fetchall()
        for log_id, area, area_raw, ip, is_foreign in logs:
            if ip and ip != "--":
                loc, foreign = resolve_ip_location(ip)
                if foreign:
                    norm_area = to_country_cn(loc or area)
                    is_for = 1
                else:
                    norm_area = to_province(loc or area, area_raw or "")
                    is_for = 0
                if norm_area != area or is_for != is_foreign:
                    cursor.execute("UPDATE visitor_logs SET area = ?, is_foreign = ? WHERE id = ?", (norm_area, is_for, log_id))

        cursor.execute("SELECT visitor_id, primary_area, primary_ip, is_foreign FROM visitor_profile")
        profiles = cursor.fetchall()
        for vid, primary_area, primary_ip, is_foreign in profiles:
            if primary_ip and primary_ip != "--":
                loc, foreign = resolve_ip_location(primary_ip)
                if foreign:
                    norm_area = to_country_cn(loc or primary_area)
                    is_for = 1
                else:
                    norm_area = to_province(loc or primary_area, "")
                    is_for = 0
                if norm_area != primary_area or is_for != is_foreign:
                    cursor.execute("UPDATE visitor_profile SET primary_area = ?, is_foreign = ? WHERE visitor_id = ?", (norm_area, is_for, vid))

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

CHINA_PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门"
]

PROVINCE_EN_TO_CN = {
    "zhejiang": "浙江", "guangdong": "广东", "beijing": "北京", "shanghai": "上海", "jiangsu": "江苏",
    "sichuan": "四川", "hubei": "湖北", "fujian": "福建", "shandong": "山东", "hunan": "湖南",
    "shaanxi": "陕西", "henan": "河南", "anhui": "安徽", "hebei": "河北", "chongqing": "重庆",
    "liaoning": "辽宁", "yunnan": "云南", "jiangxi": "江西", "guangxi": "广西", "shanxi": "山西",
    "heilongjiang": "黑龙江", "tianjin": "天津", "guizhou": "贵州", "jilin": "吉林", "inner mongolia": "内蒙古",
    "xinjiang": "新疆", "gansu": "甘肃", "hainan": "海南", "ningxia": "宁夏", "qinghai": "青海", "tibet": "西藏",
    "hong kong": "香港", "macau": "澳门", "taiwan": "台湾"
}

COUNTRY_EN_TO_CN = {
    "japan": "日本", "tokyo": "日本", "osaka": "日本", "kyoto": "日本", "jp": "日本",
    "united states": "美国", "usa": "美国", "us": "美国", "california": "美国", "new york": "美国",
    "singapore": "新加坡", "sg": "新加坡",
    "germany": "德国", "berlin": "德国", "de": "德国",
    "canada": "加拿大", "toronto": "加拿大", "vancouver": "加拿大", "ca": "加拿大",
    "united kingdom": "英国", "uk": "英国", "great britain": "英国", "england": "英国", "london": "英国", "gb": "英国",
    "netherlands": "荷兰", "amsterdam": "荷兰", "nl": "荷兰",
    "australia": "澳大利亚", "sydney": "澳大利亚", "au": "澳大利亚",
    "france": "法国", "paris": "法国", "fr": "法国",
    "korea": "韩国", "south korea": "韩国", "seoul": "韩国", "kr": "韩国",
    "russia": "俄罗斯", "moscow": "俄罗斯", "ru": "俄罗斯",
    "india": "印度", "in": "印度",
    "vietnam": "越南", "thailand": "泰国", "malaysia": "马来西亚",
    "philippines": "菲律宾", "indonesia": "印度尼西亚"
}

CITY_TO_PROVINCE = {
    "广州": "广东", "深圳": "广东", "珠海": "广东", "汕头": "广东", "佛山": "广东", "韶关": "广东", "湛江": "广东", "肇庆": "广东", "江门": "广东", "茂名": "广东", "惠州": "广东", "梅州": "广东", "汕尾": "广东", "河源": "广东", "阳江": "广东", "清远": "广东", "东莞": "广东", "中山": "广东", "潮州": "广东", "揭阳": "广东", "云浮": "广东",
    "guangzhou": "广东", "shenzhen": "广东", "dongguan": "广东", "foshan": "广东",
    "nanning": "广西", "liuzhou": "广西", "guilin": "广西", "南宁": "广西", "柳州": "广西", "桂林": "广西",
    "hangzhou": "浙江", "ningbo": "浙江", "wenzhou": "浙江", "杭州": "浙江", "宁波": "浙江", "温州": "浙江",
    "nanjing": "江苏", "wuxi": "江苏", "suzhou": "江苏", "南京": "江苏", "无锡": "江苏", "苏州": "江苏",
    "chengdu": "四川", "成都": "四川",
    "wuhan": "湖北", "武汉": "湖北",
    "hefei": "安徽", "合肥": "安徽",
    "fuzhou": "福建", "xiamen": "福建", "福州": "福建", "厦门": "福建",
    "jinan": "山东", "qingdao": "山东", "济南": "山东", "青岛": "山东",
    "changsha": "湖南", "长沙": "湖南",
    "xian": "陕西", "西安": "陕西",
    "zhengzhou": "河南", "郑州": "河南"
}

def to_country_cn(name):
    if not name or name in ("未知", "--"):
        return "未知"
    name_lower = name.lower().strip()
    if name_lower in COUNTRY_EN_TO_CN:
        return COUNTRY_EN_TO_CN[name_lower]
    for en_k, cn_v in COUNTRY_EN_TO_CN.items():
        if en_k in name_lower:
            return cn_v
    if any(c in name for c in ["日", "美", "新", "德", "加", "英", "荷", "澳", "法", "韩", "俄", "印", "越", "泰", "菲"]):
        return name
    return name if len(name) <= 10 else "未知"

def to_province(area_name, area_raw=""):
    if not area_name:
        area_name = ""
        
    lower_area = area_name.lower().strip()
    lower_raw = area_raw.lower().strip()

    if lower_area in PROVINCE_EN_TO_CN:
        return PROVINCE_EN_TO_CN[lower_area]

    for en_key, cn_val in PROVINCE_EN_TO_CN.items():
        if en_key in lower_area or en_key in lower_raw:
            return cn_val

    if area_name in CHINA_PROVINCES:
        return area_name
    for prov in CHINA_PROVINCES:
        if prov in area_name or prov in area_raw:
            return prov

    if area_name in CITY_TO_PROVINCE:
        return CITY_TO_PROVINCE[area_name]
    if lower_area in CITY_TO_PROVINCE:
        return CITY_TO_PROVINCE[lower_area]

    for city, prov in CITY_TO_PROVINCE.items():
        if city in area_name or city in area_raw or city in lower_area or city in lower_raw:
            return prov

    if lower_area in ("china", "cn", "中国", ""):
        return "未知"

    return area_name

ip_geo_cache = {}

def resolve_ip_location(ip):
    if not ip or ip in ("--", "127.0.0.1", "localhost"):
        return "未知", False
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
                    loc = to_province(region_name or city_name, f"{region_name} {city_name}")
                    if loc in ("China", "中国", "未知", ""):
                        try:
                            pc_url = f"http://whois.pconline.com.cn/ipJson.jsp?ip={ip}&json=true"
                            pc_req = urllib.request.Request(pc_url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(pc_req, timeout=3) as pc_resp:
                                pc_data = json.loads(pc_resp.read().decode('gbk', errors='replace'))
                                pro = pc_data.get("pro", "").strip()
                                city = pc_data.get("city", "").strip()
                                loc = to_province(pro, f"{pro} {city}")
                        except Exception:
                            pass
                else:
                    loc = to_country_cn(country_name or "国外")
                if loc in ("China", "中国"):
                    loc = "未知"
                ip_geo_cache[ip] = (loc, is_foreign)
                return loc, is_foreign
    except Exception:
        pass

    try:
        url = f"http://whois.pconline.com.cn/ipJson.jsp?ip={ip}&json=true"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            content = resp.read().decode('gbk', errors='replace')
            data = json.loads(content)
            pro = data.get("pro", "").strip()
            city = data.get("city", "").strip()
            addr = data.get("addr", "").strip()
            if pro:
                loc = to_province(pro, f"{pro} {city} {addr}")
                if loc not in ("China", "中国", "未知", ""):
                    ip_geo_cache[ip] = (loc, False)
                    return loc, False
    except Exception:
        pass

    return "未知", False

def is_china_location(area_raw="", area_name=""):
    if not area_raw: area_raw = ""
    if not area_name: area_name = ""
    if any(k in area_raw or k in area_name for k in ["China", "中国", "CN"]):
        return True
    for prov in CHINA_PROVINCES:
        if prov in area_raw or prov in area_name:
            return True
    for city in CITY_TO_PROVINCE:
        if city in area_raw or city in area_name:
            return True
    return False

def get_churn_analysis():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT visitor_id, visit_date
            FROM visitor_daily_active
            ORDER BY visitor_id, visit_date ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {
                "sticky_user_count": 0,
                "avg_cultivation_days": 0.0,
                "gap_laoke": 0.0,
                "gap_xinke": 0.0,
                "gap_chongfan": 0.0,
                "gap_chenji": 0.0,
                "tier_counts": {"7-13": 0, "14-29": 0, ">=30": 0},
                "tier_pcts": {"7-13": 0.0, "14-29": 0.0, ">=30": 0.0},
                "reactivated_by_tier": {"7-13": 0, "14-29": 0, ">=30": 0},
                "single_visit_count": 0,
                "repeat_visitor_count": 0,
                "churn_total_count": 0
            }
            
        v_dates_map = {}
        for vid, vdate in rows:
            if vid not in v_dates_map:
                v_dates_map[vid] = []
            if vdate not in v_dates_map[vid]:
                v_dates_map[vid].append(vdate)

        today_dt = datetime.now().date()
        
        sticky_users = []
        cultivation_days_list = []
        xinke_gaps = []
        laoke_gaps = []
        chongfan_gaps = []
        chenji_days_list = []
        
        single_visit_count = 0
        repeat_visitor_count = 0
        
        tier_counts = {"7-13": 0, "14-29": 0, ">=30": 0}
        
        for vid, dates in v_dates_map.items():
            dt_list = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
            cnt = len(dt_list)
            
            if cnt == 1:
                single_visit_count += 1
            else:
                repeat_visitor_count += 1
                
            if cnt >= 3:
                sticky_users.append(vid)
                c_days = (dt_list[2] - dt_list[0]).days
                cultivation_days_list.append(c_days)
                
            if cnt >= 2:
                xinke_gaps.append((dt_list[1] - dt_list[0]).days)
                for i in range(1, cnt):
                    gap = (dt_list[i] - dt_list[i-1]).days
                    laoke_gaps.append(gap)
                    if gap >= 3:
                        chongfan_gaps.append(gap)

            last_dt = dt_list[-1]
            dormant_days = (today_dt - last_dt).days
            
            if dormant_days >= 7:
                chenji_days_list.append(dormant_days)
                if 7 <= dormant_days <= 13:
                    tier_counts["7-13"] += 1
                elif 14 <= dormant_days <= 29:
                    tier_counts["14-29"] += 1
                elif dormant_days >= 30:
                    tier_counts[">=30"] += 1

        total_v = len(v_dates_map)
        tier_pcts = {
            k: round((v / total_v) * 100, 1) if total_v > 0 else 0.0
            for k, v in tier_counts.items()
        }
        
        avg_f = lambda lst: round(sum(lst) / len(lst), 1) if lst else 0.0

        return {
            "sticky_user_count": len(sticky_users),
            "avg_cultivation_days": avg_f(cultivation_days_list),
            "gap_laoke": avg_f(laoke_gaps),
            "gap_xinke": avg_f(xinke_gaps),
            "gap_chongfan": avg_f(chongfan_gaps),
            "gap_chenji": avg_f(chenji_days_list),
            "tier_counts": tier_counts,
            "tier_pcts": tier_pcts,
            "reactivated_by_tier": {"7-13": 0, "14-29": 0, ">=30": 0},
            "single_visit_count": single_visit_count,
            "repeat_visitor_count": repeat_visitor_count,
            "churn_total_count": sum(tier_counts.values())
        }
    except Exception as e:
        print(f"[ERROR] Churn analysis calculation failed: {e}")
        return {
            "sticky_user_count": 0,
            "avg_cultivation_days": 0.0,
            "gap_laoke": 0.0,
            "gap_xinke": 0.0,
            "gap_chongfan": 0.0,
            "gap_chenji": 0.0,
            "tier_counts": {"7-13": 0, "14-29": 0, ">=30": 0},
            "tier_pcts": {"7-13": 0.0, "14-29": 0.0, ">=30": 0.0},
            "reactivated_by_tier": {"7-13": 0, "14-29": 0, ">=30": 0},
            "single_visit_count": 0,
            "repeat_visitor_count": 0,
            "churn_total_count": 0
        }

def parse_baidu_lvt_dates(lvt_raw):
    if not lvt_raw or not isinstance(lvt_raw, str):
        return []
    
    parts = lvt_raw.split('|')
    ts_part = parts[-1] if len(parts) > 1 else parts[0]
    
    dates = set()
    bj_tz = timezone(timedelta(hours=8))
    for item in ts_part.split(','):
        item = item.strip()
        if not item.isdigit():
            continue
        try:
            val = int(item)
            if val > 1000000000000:
                val = val // 1000
            if 1000000000 <= val <= 2000000000:
                dt_bj = datetime.fromtimestamp(val, tz=bj_tz)
                d_str = dt_bj.strftime("%Y-%m-%d")
                if not d_str.startswith("2027"):
                    dates.add(d_str)
        except Exception:
            pass
            
    return sorted(list(dates))

def save_visitor_records(records):
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
            area = r.get("area", "未知")
            area_raw = r.get("area_raw", "")
            ip = r.get("ip_str", "")
            is_foreign = 1 if r.get("is_foreign", False) else 0
            first_seen_at = r.get("first_seen_at", visit_time)
            lvt_dates = r.get("lvt_dates", [])

            cursor.execute("SELECT first_seen_at FROM visitor_profile WHERE visitor_id = ?", (vid,))
            row = cursor.fetchone()
            if row and row[0]:
                existing_first = row[0][:10]
                if existing_first < first_seen_at[:10]:
                    first_seen_at = row[0]

            first_seen_date = first_seen_at[:10]
            if first_seen_date < visit_date:
                visitor_type = "老访客"
            else:
                visitor_type = "新访客"

            cursor.execute("""
                INSERT OR IGNORE INTO visitor_logs 
                (visitor_id, visit_time, visit_date, hour, area, area_raw, ip, visitor_type, is_foreign, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (vid, visit_time, visit_date, hour, area, area_raw, ip, visitor_type, is_foreign, now_str))

            cursor.execute("""
                INSERT OR IGNORE INTO visitor_daily_active
                (visitor_id, visit_date, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (vid, visit_date, first_seen_at, now_str))

            for lvt_d in lvt_dates:
                clean_lvt_d = (lvt_d or "")[:10]
                if clean_lvt_d and clean_lvt_d <= visit_date:
                    cursor.execute("""
                        INSERT OR IGNORE INTO visitor_daily_active
                        (visitor_id, visit_date, first_seen_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    """, (vid, clean_lvt_d, first_seen_at, now_str))

            cursor.execute("""
                INSERT INTO visitor_profile (visitor_id, primary_area, primary_ip, is_foreign, first_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(visitor_id) DO UPDATE SET
                    primary_area = excluded.primary_area,
                    primary_ip = excluded.primary_ip,
                    is_foreign = excluded.is_foreign,
                    first_seen_at = CASE 
                        WHEN visitor_profile.first_seen_at IS NULL 
                          OR excluded.first_seen_at < visitor_profile.first_seen_at
                        THEN excluded.first_seen_at 
                        ELSE visitor_profile.first_seen_at 
                    END
            """, (vid, area, ip, is_foreign, first_seen_at))
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Save visitor records failed: {e}")

def fetch_posthog_latest_data():
    posthog_cfg = config.get("posthog") or {}
    host = posthog_cfg.get("api_host") or "https://us.i.posthog.com"
    project_id = posthog_cfg.get("project_id") or "593531"
    personal_key = posthog_cfg.get("personal_api_key") or "phx_SCPceWtmJ6Es8gEy5gsjS4CiYUN8cQ5VGZL32QbhLUVKngiJ"

    if not (project_id and personal_key):
        print("[WARNING] PostHog API credentials not set.")
        return None

    url = f"{host}/api/projects/{project_id}/events/?limit=500"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {personal_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    })
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get("results", [])

            records = []
            for item in results:
                props = item.get("properties", {})
                
                # Rule 1: MUST HAVE client_event_time! Otherwise DISCARD IMMEDIATELY!
                client_event_time = props.get("client_event_time")
                if not client_event_time or not isinstance(client_event_time, str):
                    continue

                try:
                    clean_ts = client_event_time.replace("Z", "").replace(" ", "T")
                    dt = datetime.strptime(clean_ts[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=8)
                except Exception:
                    try:
                        ts_str = item.get("timestamp", "").replace("Z", "").replace(" ", "T")
                        dt = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=8)
                    except Exception:
                        dt = datetime.now()

                distinct_id = props.get("global_visitor_id") or item.get("distinct_id")
                if not distinct_id:
                    continue

                # Rule 2: MUST USE real_ip!
                real_ip = props.get("real_ip") or props.get("$ip") or ""
                if not real_ip:
                    continue

                loc, is_foreign = resolve_ip_location(real_ip)

                # Rule 3: Parse baidu_lvt_raw historical visit dates
                baidu_lvt_raw = props.get("baidu_lvt_raw")
                lvt_dates = parse_baidu_lvt_dates(baidu_lvt_raw) if baidu_lvt_raw else []

                visit_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                event_date_str = dt.strftime("%Y-%m-%d")

                if lvt_dates:
                    earliest_date = lvt_dates[0]
                    if earliest_date < event_date_str:
                        first_seen_at = f"{earliest_date} 00:00:00"
                    else:
                        first_seen_at = visit_time_str
                else:
                    first_seen_at = visit_time_str

                records.append({
                    "visitor_id": distinct_id,
                    "dt": dt,
                    "hour": dt.hour,
                    "area": loc,
                    "area_raw": loc,
                    "ip_str": real_ip,
                    "is_foreign": is_foreign,
                    "first_seen_at": first_seen_at,
                    "lvt_dates": lvt_dates
                })

            if records:
                records.sort(key=lambda x: x["dt"])
                save_visitor_records(records)
                print(f"[INFO] Processed & saved {len(records)} valid PostHog events to DB.")
                return True
    except Exception as e:
        print(f"[ERROR] PostHog fetch failed: {e}")
        return None

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
            if item["type"] == "new":
                existing["new_count"] = existing.get("new_count", 0) + 1
            else:
                existing["old_count"] = existing.get("old_count", 0) + 1
        else:
            new_cnt = 1 if item["type"] == "new" else 0
            old_cnt = 1 if item["type"] == "old" else 0
            hour_regions.append({
                "name": item["name"],
                "count": 1,
                "new_count": new_cnt,
                "old_count": old_cnt,
                "is_foreign": item["is_foreign"]
            })

    for h in range(24):
        if hourly_geo[h]["status"] == "active":
            hourly_geo[h]["regions"].sort(key=lambda x: x["count"], reverse=True)
            
    return hourly_geo


metrics_cache = {"data": None, "last_update": 0}
cache_lock = threading.Lock()

def insert_stats(stars, downloads):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO stats_history (timestamp, stars, downloads) VALUES (?, ?, ?)",
            (now_str, stars, downloads)
        )
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
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_dt = datetime.now()
        thirty_mins_ago = (now_dt - timedelta(minutes=30)).isoformat()
        cursor.execute(
            "SELECT timestamp, stars, downloads FROM stats_history WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
            (thirty_mins_ago,)
        )
        row = cursor.fetchone()
        
        cursor.execute("SELECT timestamp FROM stats_history ORDER BY timestamp ASC LIMIT 1")
        first_row = cursor.fetchone()
        
        conn.close()

        is_warmup = True
        minutes_tracked = 0
        if first_row:
            try:
                first_dt = datetime.fromisoformat(first_row[0])
                diff_minutes = (now_dt - first_dt).total_seconds() / 60
                minutes_tracked = int(diff_minutes)
                if diff_minutes >= 30:
                    is_warmup = False
            except Exception:
                pass

        if not row:
            return 0, 0, is_warmup, minutes_tracked

        closest_record = row
        star_delta = current_stars - closest_record[1]
        download_delta = current_downloads - closest_record[2]
        return max(0, star_delta), max(0, download_delta), is_warmup, minutes_tracked
    except Exception as e:
        print(f"[ERROR] Delta calculation failed: {e}")
        return 0, 0, True, 0

def fetch_github_data():
    repo = "liliBestCoder/ghost-proxifier-pro"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if config.get("github_token"):
        headers["Authorization"] = f"token {config['github_token']}"
        
    stars_url = f"https://api.github.com/repos/{repo}"
    req_stars = urllib.request.Request(stars_url, headers=headers)
    
    msi_ver = config.get("msi_version", "v1.1.5").strip()
    if msi_ver and not msi_ver.startswith("v"):
        tag_name = f"v{msi_ver}"
    else:
        tag_name = msi_ver or "v1.1.5"

    release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag_name}"
    req_release = urllib.request.Request(release_url, headers=headers)
    
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req_stars, context=ssl_ctx, timeout=10) as response:
            repo_info = json.loads(response.read().decode('utf-8'))
            stars = repo_info.get("stargazers_count", 0)
            
        downloads = 0
        try:
            with urllib.request.urlopen(req_release, context=ssl_ctx, timeout=10) as response:
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

def get_persisted_day_stats(date_str):
    try:
        if len(date_str) == 8:
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        else:
            formatted_date = date_str
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
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
        """, (formatted_date,))
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
            if (not area or area in ("其他", "China", "中国", "未知")) and ip_str and ip_str != "--":
                resolved_loc, resolved_foreign = resolve_ip_location(ip_str)
                if resolved_loc not in ("其他", "China", "中国", "未知"):
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
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute("""
            INSERT OR IGNORE INTO visitor_daily_active (visitor_id, visit_date, first_seen_at, updated_at)
            SELECT 
                visitor_id, 
                visit_date, 
                MIN(visit_time) as first_seen_at,
                ? as updated_at
            FROM visitor_logs
            WHERE visit_date >= ?
            GROUP BY visitor_id, visit_date
        """, (now_str, yesterday_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Async sync visitor_daily_active failed: {e}")

def get_visitor_retention_stats():
    try:
        sync_visitor_daily_active_from_logs()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT visitor_id, visit_date
            FROM visitor_daily_active
            ORDER BY visitor_id, visit_date ASC
        """)
        v_dates_map = {}
        for vid, vdate in cursor.fetchall():
            if vid not in v_dates_map:
                v_dates_map[vid] = set()
            v_dates_map[vid].add(vdate)

        cursor.execute("SELECT visitor_id, first_seen_at FROM visitor_profile")
        v_fseen_map = {}
        for vid, fseen in cursor.fetchall():
            if fseen:
                fdate = fseen[:10]
                if fdate.startswith("2027-"):
                    fdate = "2026-" + fdate[5:]
                v_fseen_map[vid] = fdate

        conn.close()
        today_str = datetime.now().strftime("%Y-%m-%d")
        all_vids = set(v_dates_map.keys()) | set(v_fseen_map.keys())
        if not all_vids:
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
            
        total_visitors = len(all_vids)
        s1 = s2 = s3 = s5 = s9 = s15 = s30 = 0

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
        today_inflow = {t: 0 for t in tier_list}

        for vid in all_vids:
            dates_set = v_dates_map.get(vid, set())
            fdate = v_fseen_map.get(vid)
            all_v_dates = set(dates_set)
            if fdate and fdate <= today_str:
                all_v_dates.add(fdate)
                
            cur_days = len(all_v_dates)
            prev_days = sum(1 for d in all_v_dates if d < today_str)
            visited_today = (today_str in all_v_dates) or (today_str in dates_set)
            
            cur_t = get_tier(cur_days)
            prev_t = get_tier(prev_days)
            
            if cur_t:
                cur_counts[cur_t] += 1
                if cur_days == 1: s1 += 1
                elif cur_days == 2: s2 += 1
                elif 3 <= cur_days <= 4: s3 += 1
                elif 5 <= cur_days <= 8: s5 += 1
                elif 9 <= cur_days <= 14: s9 += 1
                elif 15 <= cur_days <= 29: s15 += 1
                elif cur_days >= 30: s30 += 1

            if visited_today and cur_t and (cur_t != prev_t):
                today_inflow[cur_t] += 1

        calc_r = lambda cnt: round((cnt / total_visitors) * 100, 1) if total_visitors > 0 else 0.0
        return {
            "total_visitors": total_visitors,
            "streak_1": s1, "ratio_1": calc_r(s1), "net_1": today_inflow['streak_1'],
            "streak_2": s2, "ratio_2": calc_r(s2), "net_2": today_inflow['streak_2'],
            "streak_3": s3, "ratio_3": calc_r(s3), "net_3": today_inflow['streak_3'],
            "streak_5": s5, "ratio_5": calc_r(s5), "net_5": today_inflow['streak_5'],
            "streak_9": s9, "ratio_9": calc_r(s9), "net_9": today_inflow['streak_9'],
            "streak_15": s15, "ratio_15": calc_r(s15), "net_15": today_inflow['streak_15'],
            "streak_30": s30, "ratio_30": calc_r(s30)
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

def get_day_visitors_detail(formatted_date):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.visitor_id, 
                   MIN(l.visit_time) as first_today_time,
                   COALESCE(p.primary_area, l.area) as area,
                   l.ip,
                   l.visitor_type,
                   COALESCE(p.is_foreign, l.is_foreign) as is_foreign,
                   l.area_raw
            FROM visitor_logs l
            LEFT JOIN visitor_profile p ON l.visitor_id = p.visitor_id
            WHERE l.visit_date = ?
            GROUP BY l.visitor_id
        """, (formatted_date,))
        rows = cursor.fetchall()
        
        visitors_detail = []
        for vid, first_time, area, ip, vtype, is_foreign, area_raw in rows:
            norm_area = to_province(area, area_raw or "")
            
            cursor.execute("""
                SELECT DISTINCT visit_date 
                FROM visitor_daily_active 
                WHERE visitor_id = ? AND visit_date <= ?
                ORDER BY visit_date ASC
            """, (vid, formatted_date))
            v_dates = [r[0] for r in cursor.fetchall()]
            if not v_dates:
                v_dates = [formatted_date]

            visitors_detail.append({
                "visitor_id": vid,
                "first_today_time": first_time,
                "area": norm_area,
                "ip": ip,
                "visitor_type": vtype or "新访客",
                "is_foreign": bool(is_foreign),
                "dates": v_dates,
                "days_count": len(v_dates),
                "first_date": v_dates[0],
                "last_date": v_dates[-1]
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
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    trend = []
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        for d_str in dates:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            w_str = weekdays[dt.weekday()]
            m_d = dt.strftime("%m-%d")
            label = f"{m_d} ({w_str})"
            
            cursor.execute("""
                SELECT DISTINCT a.visitor_id, 
                       COALESCE(substr(p.first_seen_at, 1, 10), substr(a.first_seen_at, 1, 10))
                FROM visitor_daily_active a
                LEFT JOIN visitor_profile p ON a.visitor_id = p.visitor_id
                WHERE a.visit_date = ?
            """, (d_str,))
            active_rows = cursor.fetchall()
            
            if not active_rows:
                cursor.execute("""
                    SELECT DISTINCT l.visitor_id, 
                           COALESCE(substr(p.first_seen_at, 1, 10), substr(l.visit_time, 1, 10), l.visit_date)
                    FROM visitor_logs l
                    LEFT JOIN visitor_profile p ON l.visitor_id = p.visitor_id
                    WHERE l.visit_date = ?
                """, (d_str,))
                active_rows = cursor.fetchall()
                
            total_uv = len(active_rows)
            new_uv = 0
            old_uv = 0
            
            if total_uv > 0:
                for vid, first_date in active_rows:
                    if first_date and first_date == d_str:
                        new_uv += 1
                    else:
                        old_uv += 1

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

    return trend

def update_stats_once():
    """
    Fetches GitHub stats and direct SQLite DB visitor metrics (visitor_logs, visitor_daily_active, visitor_profile),
    updating the in-memory cache for dashboard API responses.
    """
    global metrics_cache
    print("[INFO] Background Tracker: Updating stats...")

    # 1. GitHub stats
    stars, downloads, msi_ver_tag = 0, 0, config.get("msi_version", "v1.1.5")
    github_status = "online"
    try:
        res = fetch_github_data()
        if res:
            stars, downloads, msi_ver_tag = res
            insert_stats(stars, downloads)
            github_status = "online"
    except Exception as e:
        print(f"[WARNING] GitHub fetch failed: {e}")
        latest = get_latest_db_stats()
        if latest:
            stars, downloads = latest
            github_status = "cached"
        else:
            github_status = "error"

    star_delta, download_delta, is_warmup, minutes_tracked = get_stats_deltas(stars, downloads)

    # 2. SQLite Database Visitor Metrics (PostHog / Direct Monitor Visitor Stats)
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    today_stats = get_persisted_day_stats(today_str)
    yesterday_stats = get_persisted_day_stats(yesterday_str)

    if today_stats:
        today_total, today_new, today_old, today_hourly, today_dist, today_hourly_geo = today_stats
    else:
        today_total, today_new, today_old, today_hourly, today_dist, today_hourly_geo = 0, 0, 0, [0]*24, [], []

    if yesterday_stats:
        yesterday_total, yesterday_new, yesterday_old, yesterday_hourly, yesterday_dist, yesterday_hourly_geo = yesterday_stats
    else:
        yesterday_total, yesterday_new, yesterday_old, yesterday_hourly, yesterday_dist, yesterday_hourly_geo = 0, 0, 0, [0]*24, [], []

    daily_trend = get_daily_uv_trend(days=14, today_total=today_total, today_new=today_new, yesterday_total=yesterday_total, yesterday_new=yesterday_new)
    retention_data = get_visitor_retention_stats()

    visitor_metric = {
        "today_total_uv": today_total,
        "today_new_uv": today_new,
        "today_old_uv": today_old,
        "yesterday_total_uv": yesterday_total,
        "yesterday_new_uv": yesterday_new,
        "yesterday_old_uv": yesterday_old,
        "today_hourly_uv": today_hourly,
        "yesterday_hourly_uv": yesterday_hourly,
        "daily_uv_trend": daily_trend,
        "status": "online"
    }

    district_metric = {
        "districts": {
            "today": today_dist,
            "yesterday": yesterday_dist
        },
        "countries": {
            "today": [d for d in today_dist if d.get("is_foreign")],
            "yesterday": [d for d in yesterday_dist if d.get("is_foreign")]
        },
        "hourly_new_geo": {
            "today": today_hourly_geo,
            "yesterday": yesterday_hourly_geo
        },
        "today_visitors_detail": get_today_visitors_detail(today_str),
        "yesterday_visitors_detail": get_day_visitors_detail(yesterday_str)
    }

    aggregated = {
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
            "msi_version": msi_ver_tag,
            "status": github_status
        },
        "baidu": visitor_metric,
        "baidu_district": district_metric,
        "retention": retention_data,
        "churn": get_churn_analysis()
    }

    # Only save to cache if we have valid non-zero stats or if cache is empty
    with cache_lock:
        if metrics_cache.get("data") is None or aggregated.get("baidu", {}).get("today_total_uv", 0) > 0:
            metrics_cache["data"] = aggregated
            metrics_cache["last_update"] = time.time()

    print("[INFO] Background Tracker: Stats updated successfully.")
    return aggregated

def get_current_metrics():
    with cache_lock:
        if metrics_cache.get("data") and metrics_cache["data"].get("baidu", {}).get("today_total_uv", 0) > 0:
            return metrics_cache["data"]
    return update_stats_once()

def bg_tracker():
    print("[INFO] Background stats tracker thread started.")
    try:
        fetch_posthog_latest_data()
        update_stats_once()
    except Exception as e:
        print(f"[ERROR] Initial background tracker run error: {e}")

    while True:
        time.sleep(60)
        try:
            fetch_posthog_latest_data()
            update_stats_once()
        except Exception as e:
            print(f"[ERROR] Background tracker loop error: {e}")

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
