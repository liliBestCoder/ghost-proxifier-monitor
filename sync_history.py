import os
import sys
import json
import sqlite3
import urllib.request
import ssl
import time
from datetime import datetime, timedelta

from monitor_server import to_province, is_china_location, resolve_ip_location, normalize_existing_db_records, extract_area_from_raw, refresh_baidu_token

# Fix UTF-8 encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

DB_FILE = 'monitor.db'
CONFIG_FILE = 'config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def init_db(conn):
    cursor = conn.cursor()
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

def fetch_baidu_history(config, days=14):
    site_id = config.get("baidu_site_id")
    access_token = config.get("baidu_access_token")
    if not (site_id and access_token):
        print("[ERROR] Missing Baidu credentials in config.json")
        return

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    conn = sqlite3.connect(DB_FILE)
    init_db(conn)
    cursor = conn.cursor()
    
    # Incrementally insert without deleting any historical data

    today = datetime.now()
    total_logs_inserted = 0
    total_daily_active_inserted = 0

    print(f"[INFO] Starting historical sync for past {days} days from Baidu Tongji API...")

    for d in range(days):
        dt_obj = today - timedelta(days=d)
        date_str = dt_obj.strftime("%Y%m%d")
        formatted_date = dt_obj.strftime("%Y/%m/%d")
        iso_date = dt_obj.strftime("%Y-%m-%d")

        url = (
            f"https://openapi.baidu.com/rest/2.0/tongji/report/getData?"
            f"access_token={access_token}&site_id={site_id}&method=trend/latest/a"
            f"&max_results=5000"
        )

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as response:
                res = json.loads(response.read().decode('utf-8'))
                if res and ("error" in res or "error_code" in res):
                    print(f"[WARNING] Baidu API error: {res}")
                    if "invalid_token" in str(res) or "expired" in str(res) or res.get("error_code") in [110, 111, 100]:
                        if refresh_baidu_token():
                            access_token = load_config().get("baidu_access_token", access_token)
                            url = (
                                f"https://openapi.baidu.com/rest/2.0/tongji/report/getData?"
                                f"access_token={access_token}&site_id={site_id}&method=trend/latest/a"
                                f"&max_results=5000"
                            )
                            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp2:
                                res = json.loads(resp2.read().decode('utf-8'))
                if not res or "result" not in res:
                    continue

                items = res["result"].get("items", [])
                if len(items) < 2:
                    continue

                details_list = items[0]
                fields_list = items[1]
                now_iso = datetime.now().isoformat()
                day_log_cnt = 0

                for idx, fval in enumerate(fields_list):
                    start_time_str = str(fval[0]) if len(fval) > 0 else ""
                    area_raw = str(fval[1]) if len(fval) > 1 else ""
                    ip_str = str(fval[5]) if len(fval) > 5 else ""
                    visitor_id = str(fval[6]) if len(fval) > 6 else ""

                    if not visitor_id or not start_time_str.startswith(formatted_date) or ip_str == "106.225.235.246":
                        continue

                    visitor_type = "新访客"
                    if idx < len(details_list) and details_list[idx] and len(details_list[idx]) > 0:
                        detail = details_list[idx][0].get("detail", {})
                        visitor_type = detail.get("visitorType", "新访客")

                    try:
                        dt = datetime.strptime(start_time_str, "%Y/%m/%d %H:%M:%S")
                    except:
                        dt = datetime.now()

                    visit_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    visit_date = dt.strftime("%Y-%m-%d")
                    hour = dt.hour

                    area_name = extract_area_from_raw(area_raw)

                    if area_name and area_name != "其他":
                        area_name = to_province(area_name, area_raw)
                        is_foreign = 0 if is_china_location(area_raw, area_name) else 1
                    elif ip_str and ip_str != "--":
                        resolved_loc, resolved_foreign = resolve_ip_location(ip_str)
                        if resolved_loc != "其他":
                            area_name = to_province(resolved_loc, area_raw)
                            is_foreign = 1 if resolved_foreign else 0
                        else:
                            area_name = "其他"
                            is_foreign = 0
                    else:
                        area_name = "其他"
                        is_foreign = 0

                    cursor.execute('''
                        INSERT OR IGNORE INTO visitor_logs
                        (visitor_id, visit_time, visit_date, hour, area, area_raw, ip, visitor_type, is_foreign, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (visitor_id, visit_time, visit_date, hour, area_name, area_raw, ip_str, visitor_type, is_foreign, now_iso))
                    if cursor.rowcount > 0:
                        total_logs_inserted += 1

                    cursor.execute('''
                        INSERT OR IGNORE INTO visitor_daily_active
                        (visitor_id, visit_date, first_seen_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    ''', (visitor_id, visit_date, visit_time, now_iso))
                    if cursor.rowcount > 0:
                        total_daily_active_inserted += 1
                        day_log_cnt += 1

                    cursor.execute('''
                        INSERT OR IGNORE INTO visitor_profile
                        (visitor_id, primary_area, primary_ip, is_foreign, first_seen_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (visitor_id, area_name, ip_str, is_foreign, visit_time))

            conn.commit()
            print(f"[SUCCESS] Date {iso_date}: Synced {day_log_cnt} unique active visitors")
            time.sleep(0.3)

        except Exception as e:
            print(f"[ERROR] Sync failed for date {iso_date}: {e}")

    conn.close()
    print(f"\n[FINISHED] Total logs inserted: {total_logs_inserted}, Daily active entries: {total_daily_active_inserted}")

if __name__ == '__main__':
    cfg = load_config()
    fetch_baidu_history(cfg, days=14)
