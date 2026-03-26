import os
import sys
import json
import random
import asyncio
import re
import secrets
import string
from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ---------------- #

def log(msg):
    # Print to stderr so we don't pollute the JSON stdout
    print(msg, file=sys.stderr)

# ---------------- COOKIE GENERATOR ---------------- #

def generate_exact_ig_cookie():
    """Generates a structurally perfect (but cryptographically invalid) IG sessionid"""
    digits = string.digits
    user_id_length = secrets.choice(range(9, 15))
    user_id = secrets.choice(string.digits[1:]) + ''.join(secrets.choice(digits) for _ in range(user_id_length - 1))
    base62 = string.ascii_letters + string.digits
    session_key = ''.join(secrets.choice(base62) for _ in range(14))
    shard_id = secrets.choice(['5', '18', '25', '28'])
    url_safe_b64 = string.ascii_letters + string.digits + "-_"
    prefix = secrets.choice(["AY", "AZ", "AX"])
    sig_body = ''.join(secrets.choice(url_safe_b64) for _ in range(37))
    signature = f"{prefix}{sig_body[:20]}-{sig_body[20:36]}"
    return f"{user_id}%3A{session_key}%3A{shard_id}%3A{signature}"

real_session = os.getenv("IG_SESSION_ID")
if real_session and real_session != "YOUR_SESSIONID_VALUE_HERE":
    SESSION_ID = real_session
    log("🟢 Using REAL Session ID from .env")
else:
    SESSION_ID = generate_exact_ig_cookie()
    log("🟡 WARNING: Using GENERATED Fake Session ID.")

PROXY_URL = os.getenv("PROXY_URL") or "http://94199cbd2c25367787f9__cr.tn,tr,tc,tv,ug,ua,ae,gb,us,uy,uz,vu,ve,vn,vg,vi,ye:10e2d1924a21f013@gw.dataimpulse.com:823"
PROXIES = {"http": PROXY_URL, "https": PROXY_URL}

BROWSER_PROFILES = [
    {"impersonate": "chrome120", "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    {"impersonate": "chrome116", "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/116.0.0.0"},
    {"impersonate": "safari15_5", "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15"},
]

def get_headers(ua):
    return {
        "User-Agent": ua,
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cookie": f"sessionid={SESSION_ID}"
    }

# ---------------- STEP 1: GET USER ID ---------------- #

async def get_user_id(username):
    url = f"https://www.instagram.com/{username}/"
    profile = random.choice(BROWSER_PROFILES)

    async with AsyncSession(impersonate=profile["impersonate"], proxies=PROXIES, verify=False) as session:
        res = await session.get(url, headers={
            "User-Agent": profile["ua"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Upgrade-Insecure-Requests": "1"
        })
        
        if res.status_code != 200:
            log(f"❌ Blocked while fetching profile HTML (Status: {res.status_code})")
            return None

        html = res.text

        # Try JSON blocks first
        shared_data_match = re.search(r'window\._sharedData\s*=\s*({.+?});</script>', html)
        if shared_data_match:
            try:
                json_data = json.loads(shared_data_match.group(1))
                user_obj = json_data.get('entry_data', {}).get('ProfilePage', [{}])[0].get('graphql', {}).get('user', {})
                if user_obj.get('id'): return user_obj.get('id')
            except: pass

        add_data_match = re.search(r'window\.__additionalDataLoaded\([^,]+,\s*({.+?})\s*\);', html)
        if add_data_match:
            try:
                json_data = json.loads(add_data_match.group(1))
                user_obj = json_data.get('graphql', {}).get('user', {})
                if user_obj.get('id'): return user_obj.get('id')
            except: pass

        # Fallback to Regex
        id_match = re.search(r'"user_id":"(\d+)"', html) or re.search(r'instagram://user\?username=.*?&id=(\d+)', html)
        return id_match.group(1) if id_match else None

# ---------------- STEP 2: GET SUGGESTED ACCOUNTS ---------------- #

async def fetch_suggested_accounts(user_id):
    profile = random.choice(BROWSER_PROFILES)
    headers = get_headers(profile["ua"])
    headers["Referer"] = f"https://www.instagram.com/"
    headers["X-Requested-With"] = "XMLHttpRequest"

    # 🔥 The hidden API endpoint for account chaining
    url = f"https://i.instagram.com/api/v1/discover/chaining/?target_id={user_id}"
    
    suggested_list = []

    async with AsyncSession(impersonate=profile["impersonate"], proxies=PROXIES, verify=False) as session:
        try:
            log(f"🌐 Fetching 'Suggested for you' API for User ID: {user_id}...")
            res = await session.get(url, headers=headers)
            
            if res.status_code != 200:
                log(f"❌ Blocked (Status {res.status_code}). Note: API might require a real Session ID in .env")
                return []

            data = res.json()
            users = data.get("users", [])

            for u in users:
                suggested_list.append({
                    "id": u.get("pk") or u.get("id"),
                    "username": u.get("username"),
                    "full_name": u.get("full_name"),
                    "profile_pic": u.get("profile_pic_url"),
                    "is_verified": u.get("is_verified", False)
                })

            return suggested_list

        except Exception as e:
            log(f"❌ Error fetching suggested accounts: {str(e)}")
            return []

# ---------------- MAIN ---------------- #

async def main():
    if len(sys.argv) > 1:
        username = sys.argv[1].strip()
    else:
        username = input("Enter IG Username (e.g., thesouledstore): ").strip()

    if not username:
        log("❌ Username required")
        sys.exit(1)

    log(f"\n🚀 Resolving User ID for @{username}...")
    user_id = await get_user_id(username)

    if not user_id:
        log("❌ Failed to get User ID. Profile might be restricted or proxy blocked.")
        sys.exit(1)
    
    log(f"✅ Found User ID: {user_id}")

    suggested_accounts = await fetch_suggested_accounts(user_id)

    # Print clean JSON array directly to stdout
    print(json.dumps(suggested_accounts, indent=2))

if __name__ == "__main__":
    asyncio.run(main())