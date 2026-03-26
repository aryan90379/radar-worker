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

TARGET_POSTS = int(sys.argv[2]) if len(sys.argv) > 2 else 12


def log(msg):
    # Print to stderr so Node.js child_process doesn't confuse it with the JSON output
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
    log("🟡 WARNING: Using GENERATED Fake Session ID. Meta will likely block this with a 401.")


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
        "X-ASBD-ID": "129477",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cookie": f"sessionid={SESSION_ID}"
    }

# ---------------- STEP 1: GET USER ID & PROFILE (HTML BYPASS) ---------------- #

# ---------------- STEP 1: GET USER ID & PROFILE (HTML BYPASS) ---------------- #

# ---------------- STEP 1: GET USER ID & PROFILE (HTML BYPASS) ---------------- #

async def get_profile_data(username):
    url = f"https://www.instagram.com/{username}/"
    profile = random.choice(BROWSER_PROFILES)

    async with AsyncSession(impersonate=profile["impersonate"], proxies=PROXIES, verify=False) as session:
        res = await session.get(url, headers={
            "User-Agent": profile["ua"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1"
        })
        
        log(f"HTML Profile Status: {res.status_code}")

        if res.status_code != 200:
            log("❌ Blocked while fetching profile HTML (IP might be flagged)")
            return None

        html = res.text

        # Anti-Bot Check: Are we looking at a login wall?
        if 'href="https://www.instagram.com/accounts/login/' in html and not 'biography' in html:
            log("❌ Hit the Login Wall. Your SESSION_ID is dead or IP is blocked.")
            return None

        # Initialize the payload
        profile_data = {
            "id": None,
            "username": username,
            "name": username,
            "biography": "",
            "profile_picture_url": "",
            "followers_count": 0,
            "follows_count": 0,
            "media_count": 0,
        }

        # ==========================================
        # LAYER 1: ROBUST JSON PARSING
        # ==========================================
        try:
            # Look for the exact chunk of JSON containing the biography 
            # This bypasses variable name changes completely
            bio_block_match = re.search(r'("user":\{"ai_agent_type".*?"username":"' + re.escape(username) + r'".*?\})', html)
            if not bio_block_match:
                # Alternative modern structure check
                bio_block_match = re.search(r'("user":\{.*?"biography":".*?\})', html)

            if bio_block_match:
                # Wrap it to make it valid JSON
                user_str = "{" + bio_block_match.group(1) + "}"
                parsed_json = json.loads(user_str).get('user', {})
                
                profile_data["id"] = parsed_json.get('id', profile_data["id"])
                profile_data["name"] = parsed_json.get('full_name', profile_data["name"])
                profile_data["biography"] = parsed_json.get('biography', profile_data["biography"])
                profile_data["profile_picture_url"] = parsed_json.get('profile_pic_url_hd') or parsed_json.get('profile_pic_url', profile_data["profile_picture_url"])
                
                # Stats might be deeply nested depending on the JSON format
                if 'edge_followed_by' in parsed_json:
                    profile_data["followers_count"] = parsed_json['edge_followed_by'].get('count', 0)
                    profile_data["follows_count"] = parsed_json['edge_follow'].get('count', 0)
                    profile_data["media_count"] = parsed_json['edge_owner_to_timeline_media'].get('count', 0)
        except Exception as e:
            log(f"⚠️ Layer 1 (JSON Parse) missed some data: {e}")


        # ==========================================
        # LAYER 2: AGGRESSIVE REGEX HUNTER (For Missing Fields)
        # ==========================================
        
        # ID Fallback
        if not profile_data["id"]:
            id_match = re.search(r'"user_id":"(\d+)"|profilePage_(\d+)|"id":"(\d+)"', html)
            if id_match:
                profile_data["id"] = next(m for m in id_match.groups() if m)

        # Biography Fallback
        if not profile_data["biography"]:
            bio_match = re.search(r'"biography":"(.*?)"(?:,"|})', html)
            if bio_match:
                try:
                    profile_data["biography"] = bio_match.group(1).encode('utf-8').decode('unicode_escape').replace("\\/", "/")
                except:
                    profile_data["biography"] = bio_match.group(1)

        # Profile Pic Fallback
        if not profile_data["profile_picture_url"]:
            pic_match = re.search(r'"profile_pic_url_hd":"([^"]+)"|"profile_pic_url":"([^"]+)"', html)
            if pic_match:
                raw_pic = next(m for m in pic_match.groups() if m)
                profile_data["profile_picture_url"] = raw_pic.encode('utf-8').decode('unicode_escape').replace("\\/", "/")


        # ==========================================
        # LAYER 3: SEO META TAGS (Bulletproof Stats)
        # ==========================================
        def parse_number(text):
            if not text: return 0
            text = text.upper().replace(',', '')
            if 'M' in text: return int(float(text.replace('M', '')) * 1000000)
            if 'K' in text: return int(float(text.replace('K', '')) * 1000)
            try: return int(float(text))
            except: return 0

        desc_match = re.search(r'<meta content="([^"]+Followers,\s*[^"]+Following,\s*[^"]+Posts[^"]*)"\s+name="description"', html, re.IGNORECASE)
        if desc_match:
            desc = desc_match.group(1)
            if not profile_data["followers_count"]:
                fm = re.search(r'([\d\.,KM]+)\s+Followers', desc, re.IGNORECASE)
                if fm: profile_data["followers_count"] = parse_number(fm.group(1))

            if not profile_data["follows_count"]:
                flm = re.search(r'([\d\.,KM]+)\s+Following', desc, re.IGNORECASE)
                if flm: profile_data["follows_count"] = parse_number(flm.group(1))

            if not profile_data["media_count"]:
                pm = re.search(r'([\d\.,KM]+)\s+Posts', desc, re.IGNORECASE)
                if pm: profile_data["media_count"] = parse_number(pm.group(1))

        # Final SEO pic check
        if not profile_data["profile_picture_url"]:
            og_image = re.search(r'property="og:image"\s+content="([^"]+)"', html)
            if og_image:
                profile_data["profile_picture_url"] = og_image.group(1).replace("&amp;", "&")

        if not profile_data["id"]:
            log("❌ Failed to parse User ID entirely.")
            return None

        return profile_data
# ---------------- STEP 2: FETCH POSTS (INTERNAL API) ---------------- #

async def fetch_posts(user_id):
    posts = []
    max_id = None
    profile = random.choice(BROWSER_PROFILES)
    headers = get_headers(profile["ua"])
    headers["Referer"] = f"https://www.instagram.com/"
    headers["X-Requested-With"] = "XMLHttpRequest"

    async with AsyncSession(impersonate=profile["impersonate"], proxies=PROXIES, verify=False) as session:
        max_pages = (TARGET_POSTS // 12) + 2  # dynamically calculate pages needed
        for page in range(max_pages):
            url = f"https://i.instagram.com/api/v1/feed/user/{user_id}/?count=12"
            if max_id:
                url += f"&max_id={max_id}"

            res = await session.get(url, headers=headers)

            if res.status_code != 200:
                log(f"❌ Blocked on page {page+1} (status {res.status_code})")
                break

            data = res.json()
            items = data.get("items", [])

            if not items:
                log("❌ No more posts available.")
                break

            posts.extend(items)
            log(f"📄 Page {page+1} → {len(items)} posts (Total: {len(posts)})")

            if len(posts) >= TARGET_POSTS:
                break
            if not data.get("more_available"):
                break
            
            max_id = data.get("next_max_id")
            if not max_id:
                break

            await asyncio.sleep(random.uniform(2.5, 4.5))

    return posts[:TARGET_POSTS]


# ---------------- STEP 3: NORMALIZE (FRONTEND ALIGNED) ---------------- #

def normalize_posts(posts):
    output = []

    for p in posts:
        caption_data = p.get("caption") or {}
        user_data = p.get("user") or {}
        coauthors_data = p.get("coauthor_producers") or []
        sponsors_data = p.get("sponsor_tags") or []
        
        video_versions = p.get("video_versions") or [{}]
        image_versions = p.get("image_versions2") or {}
        image_candidates = image_versions.get("candidates") or [{}]
        
        media_url = (
            video_versions[0].get("url")
            if p.get("media_type") == 2 and video_versions
            else image_candidates[0].get("url") if image_candidates else None
        )

        caption_text = caption_data.get("text", "")

        # Combine brands for the UI
        creator_username = user_data.get("username")
        creator_obj = [{"username": creator_username}] if creator_username else []
        
        seen = set()
        combined_brands = []
        for b in (creator_obj + coauthors_data + sponsors_data):
            if isinstance(b, dict):
                uname = b.get("username") or b.get("handle")
                if uname and uname not in seen:
                    seen.add(uname)
                    combined_brands.append({"username": uname})

        output.append({
            "id": p.get("id") or p.get("pk"),
            "shortcode": p.get("code"),
            "caption": caption_text,
            "media_type": "VIDEO" if p.get("media_type") == 2 else "IMAGE",
            "media_url": media_url,
            "permalink": f"https://instagram.com/p/{p.get('code')}/" if p.get("code") else None,
            "like_count": p.get("like_count") or 0,
            "comments_count": p.get("comment_count") or 0,
            "play_count": p.get("play_count") or 0,
            "timestamp": p.get("taken_at") * 1000 if p.get("taken_at") else None, # Javascript uses ms
            
            # 🔥 Custom Frontend Flags
            "creator": creator_username,
            "isOfficialBrand": len(sponsors_data) > 0,
            "officialBrands": combined_brands,
            "detectedBrands": re.findall(r'@[\w\.-]+', caption_text)
        })

    return output


# ---------------- MAIN ---------------- #

async def main():
    if len(sys.argv) < 2:
        log("❌ Username argument required")
        sys.exit(1)

    username = sys.argv[1].strip()
    log(f"\n🚀 Scraping @{username}...\n")

    profile_data = await get_profile_data(username)

    if not profile_data:
        log("❌ Failed to get profile data (proxy or IG blocked)")
        sys.exit(1)
    
    log(f"✅ Found User ID: {profile_data['id']}")

    posts = await fetch_posts(profile_data['id'])
    normalized = normalize_posts(posts)

    # 📁 Output directly to stdout for Express to read!
    final_payload = {
        "profile": profile_data,
        "recentPosts": normalized
    }

    # Print JSON exactly once
    print(json.dumps(final_payload))


if __name__ == "__main__":
    asyncio.run(main())