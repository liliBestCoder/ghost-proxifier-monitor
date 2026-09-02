import sys
import json
import urllib.request
import urllib.parse

# Reconfigure stdout to use UTF-8 to prevent GBK encoding errors in Windows terminal
sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "9BmLS2WaCBxa8GlAfnvfI12po5DsWisD"
SECRET_KEY = "gHCkp5ndOR3vWBmw7a6zvV18ClOxjZhy"
REDIRECT_URI = "oob"

def exchange_code(code):
    print(f"正在向百度开放平台请求 exchange access_token (code: {code})...")
    url = "https://openapi.baidu.com/oauth/2.0/token"
    params = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": API_KEY,
        "client_secret": SECRET_KEY,
        "redirect_uri": REDIRECT_URI
    }
    
    data = urllib.parse.urlencode(params).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            
        access_token = res_data.get("access_token")
        refresh_token = res_data.get("refresh_token")
        
        if not access_token:
            print("[错误] 未能在返回的数据中找到 access_token，返回结果为:")
            print(json.dumps(res_data, indent=4, ensure_ascii=False))
            return False
            
        print("\n==================================================")
        print("[成功] 成功获取 Access Token 凭证！")
        print(f"Access Token: {access_token}")
        print(f"Refresh Token: {refresh_token}")
        print("==================================================")
        
        # Save to config.json
        config_path = "config.json"
        config = {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except:
            pass
            
        config["baidu_access_token"] = access_token
        if refresh_token:
            config["baidu_refresh_token"] = refresh_token
        # Keep other credentials intact
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            
        print("[信息] 凭证已成功保存写入至 config.json，监控服务将自动重载应用。")
        return True
    except Exception as e:
        print(f"[错误] 请求百度 API 换取 Token 失败: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用说明:")
        print("  python get_token.py <YOUR_AUTHORIZATION_CODE>")
        sys.exit(1)
        
    code_val = sys.argv[1].strip()
    success = exchange_code(code_val)
    sys.exit(0 if success else 1)
