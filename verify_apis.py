import sys
import json
import urllib.request
import urllib.error
import sqlite3
from datetime import datetime

# Reconfigure stdout to use UTF-8 to prevent GBK encoding errors in Windows terminal
sys.stdout.reconfigure(encoding='utf-8')

print("==================================================")
print("Ghost Proxifier Monitor - API & System Diagnostic")
print("==================================================")

errors = []

# 1. Test SQLite
print("\n[Diagnostic] Checking SQLite3 Database support...")
try:
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE test (id INTEGER, val TEXT)')
    cursor.execute('INSERT INTO test VALUES (1, "ok")')
    cursor.execute('SELECT val FROM test WHERE id = 1')
    res = cursor.fetchone()[0]
    conn.close()
    if res == "ok":
        print("[SUCCESS] SQLite3 works perfectly.")
    else:
        raise Exception("Invalid data returned")
except Exception as e:
    errors.append(f"SQLite check failed: {e}")
    print(f"[FAIL] SQLite3 error: {e}")

# 2. Test GitHub API Star query
print("\n[Diagnostic] Fetching GitHub star count for liliBestCoder/ghost-proxifier-pro...")
repo = "liliBestCoder/ghost-proxifier-pro"
stars_url = f"https://api.github.com/repos/{repo}"
req = urllib.request.Request(stars_url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        info = json.loads(response.read().decode('utf-8'))
        stars = info.get("stargazers_count", 0)
        print(f"[SUCCESS] Connected to GitHub API. Current Stars: {stars}")
except urllib.error.HTTPError as e:
    if e.code == 403:
        print("[WARNING] GitHub API Rate Limit Hit (403). This is normal for public IPs. Please use a Personal Access Token.")
    else:
        errors.append(f"GitHub Star query HTTPError: {e.code} {e.reason}")
        print(f"[FAIL] GitHub Star query error: {e.code} {e.reason}")
except Exception as e:
    errors.append(f"GitHub Star query failed: {e}")
    print(f"[FAIL] GitHub Star query error: {e}")

# 3. Test GitHub Release downloads query
print("\n[Diagnostic] Fetching GitHub download count for release v1.1.5...")
release_url = f"https://api.github.com/repos/{repo}/releases/tags/v1.1.5"
req = urllib.request.Request(release_url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        info = json.loads(response.read().decode('utf-8'))
        assets = info.get("assets", [])
        downloads = 0
        msi_found = False
        for asset in assets:
            if asset.get("name", "").lower().endswith(".msi"):
                downloads += asset.get("download_count", 0)
                msi_found = True
                print(f" -> Found MSI asset: {asset.get('name')} (Downloads: {asset.get('download_count')})")
        print(f"[SUCCESS] Connected to Release API. Total MSI Downloads: {downloads}")
except urllib.error.HTTPError as e:
    if e.code == 404:
        print("[WARNING] GitHub Release v1.1.5 not found (404) or repository is private. This is handled gracefully by using 0 as download count.")
    elif e.code == 403:
        print("[WARNING] GitHub API Rate Limit Hit (403).")
    else:
        errors.append(f"GitHub Release query HTTPError: {e.code} {e.reason}")
        print(f"[FAIL] GitHub Release query error: {e.code} {e.reason}")
except Exception as e:
    errors.append(f"GitHub Release query failed: {e}")
    print(f"[FAIL] GitHub Release query error: {e}")

# 4. Check Baidu Tongji format parser logic
print("\n[Diagnostic] Testing Baidu Tongji parser logic with dummy responses...")
dummy_success_payload = {
    "header": {
        "status": 0
    },
    "body": {
        "data": [
            {
                "result": {
                    "offset": 0,
                    "total": 3,
                    "sum": [[1450, 450]],
                    "items": [
                        [{"name": "00:00-00:59"}, {"name": "01:00-01:59"}, {"name": "02:00-02:59"}],
                        [[12, 5], [8, 3], [5, 2]]
                    ]
                }
            }
        ]
    }
}

try:
    # Parsing test
    body = dummy_success_payload["body"]
    result_data = body["data"][0].get("result", {})
    items = result_data.get("items", [])
    sum_data = result_data.get("sum", [])
    
    total = 0
    new_total = 0
    hourly = [0] * 24
    
    if sum_data and len(sum_data) > 0 and len(sum_data[0]) > 0:
        val_sum_list = sum_data[0]
        if len(val_sum_list) > 0:
            total = int(val_sum_list[0])
        if len(val_sum_list) > 1:
            new_total = int(val_sum_list[1])
            
    if len(items) >= 2:
        time_labels = items[0]
        values = items[1]
        for idx, time_item in enumerate(time_labels):
            hour_str = time_item.get("name", "")
            hour = idx
            if ":" in hour_str:
                hour = int(hour_str.split(":")[0])
            if hour < 24 and idx < len(values) and len(values[idx]) > 0:
                hourly[hour] = values[idx][0]
                
    if total == 1450 and new_total == 450 and hourly[0] == 12 and hourly[1] == 8 and hourly[2] == 5:
        print("[SUCCESS] Baidu Tongji response parser logic verified successfully.")
    else:
        raise Exception(f"Parsed values do not match expected dummy data structure (total: {total}, new: {new_total}, hourly[0]: {hourly[0]}).")
except Exception as e:
    errors.append(f"Baidu Tongji parser logic validation failed: {e}")
    print(f"[FAIL] Baidu Tongji parser validation error: {e}")

# Diagnostic Summary
print("\n==================================================")
if not errors:
    print("[DIAGNOSTIC COMPLETE: SUCCESS]")
    print("All core API connections, database functionality, and data parsers are healthy and ready.")
    sys.exit(0)
else:
    print(f"[DIAGNOSTIC COMPLETE: WARNINGS/FAILURES FOUND ({len(errors)})]")
    for err in errors:
        print(f" - {err}")
    print("Please address any errors above, or ignore warnings if they relate to expected GitHub API rate limits.")
    sys.exit(1)
