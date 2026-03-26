import os
import sys
import json
import random
import asyncio
import re
from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ---------------- #

def log(msg):
    # Print to stderr so we don't pollute the JSON stdout
    print(msg, file=sys.stderr)

PROXY_URL = os.getenv("PROXY_URL") or "http://94199cbd2c25367787f9__cr.tn,tr,tc,tv,ug,ua,ae,gb,us,uy,uz,vu,ve,vn,vg,vi,ye:10e2d1924a21f013@gw.dataimpulse.com:823"
PROXIES = {"http": PROXY_URL, "https": PROXY_URL}

BROWSER_PROFILES = [
    {"impersonate": "chrome120", "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    {"impersonate": "chrome116", "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/116.0.0.0"},
    {"impersonate": "safari15_5", "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15"},
]

# Get real session if it exists.
real_session = os.getenv("IG_SESSION_ID")
if real_session and real_session != "YOUR_SESSIONID_VALUE_HERE":
    log("🟢 Using REAL Session ID from .env")
else:
    real_session = None
    log("🟡 WARNING: No Session ID found. Using Guest Mode (Embed Bypass).")

def extract_shortcode(url):
    """Extracts shortcode from various IG URL formats."""
    if "instagram.com" in url:
        match = re.search(r'/(?:reels|reel|p)/([^/?&]+)', url)
        if match:
            return match.group(1)
    return url.strip()

# ---------------- EMBED BYPASS SCRAPER LOGIC ---------------- #

async def fetch_media_data_embed(shortcode):
    log(f"🔍 Using Shortcode: '{shortcode}'")

    url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    profile = random.choice(BROWSER_PROFILES)

    headers = {
        "User-Agent": profile["ua"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Upgrade-Insecure-Requests": "1"
    }

    if real_session:
        headers["Cookie"] = f"sessionid={real_session}"

    async with AsyncSession(impersonate=profile["impersonate"], proxies=PROXIES, verify=False) as session:
        try:
            log(f"🌐 Fetching Embed Data for {shortcode}...")
            response = await session.get(url, headers=headers, timeout=20)
            
            if response.status_code != 200:
                log(f"❌ Blocked: HTTP {response.status_code}")
                return None

            html = response.text

            if "Login • Instagram" in html or "You must log in" in html:
                log("❌ Instagram served a login wall even on the embed endpoint.")
                return None

            # --- CLEAN THE HTML FOR REGEX FALLBACK ---
            # IG escapes quotes (\") inside the HTML. We must unescape them to regex effectively.
            clean_html = html.replace('\\"', '"').replace('\\/', '/')

            # --- EXTRACT THE HIDDEN JSON PAYLOAD ---
            json_payload = None
            
            match = re.search(r'window\.__additionalDataLoaded\([^,]+,\s*({.+?})\s*\);', html)
            if match:
                try:
                    json_payload = json.loads(match.group(1)).get('shortcode_media', {})
                except: pass

            if not json_payload:
                blob_match = re.search(r'({"shortcode_media":{.*?"id":"[^"]+".*?})<', clean_html)
                if blob_match:
                    try:
                        parsed = json.loads(blob_match.group(1))
                        json_payload = parsed.get("shortcode_media")
                    except: pass

            # --- PARSE THE DATA (IF JSON IS CLEAN) ---
            if json_payload:
                video_url = json_payload.get('video_url')
                image_url = json_payload.get('display_url')
                
                edges = json_payload.get('edge_media_to_caption', {}).get('edges', [])
                caption = edges[0].get('node', {}).get('text', '') if edges else ""

                coauthors_data = json_payload.get('coauthor_producers', [])
                collaborators = [c.get('username') for c in coauthors_data if c.get('username')]

                tagged_edges = json_payload.get('edge_media_to_tagged_user', {}).get('edges', [])
                tagged_users = [t.get('node', {}).get('user', {}).get('username') for t in tagged_edges if t.get('node', {}).get('user', {}).get('username')]

                main_author = json_payload.get('owner', {}).get('username', 'unknown')
                if main_author not in collaborators and main_author != 'unknown':
                    collaborators.insert(0, main_author)

                return {
                    "shortcode": shortcode,
                    "type": "VIDEO" if video_url else "IMAGE",
                    "video_url": video_url,
                    "image_url": image_url,
                    "author": main_author,
                    "collaborators": collaborators,
                    "tagged_users": tagged_users,
                    "caption": caption,
                    "likes": json_payload.get('edge_media_preview_like', {}).get('count', 0),
                    "comments": json_payload.get('comment', {}).get('count', 0),
                    "plays": json_payload.get('video_view_count', 0),
                    "timestamp": json_payload.get('taken_at_timestamp') # 🔥 ADDED THIS
                }

            # --- FALLBACK: AGGRESSIVE RAW HTML SCRAPING ---
            log("⚠️ JSON payload not found, falling back to aggressive HTML/Regex parsing...")
            
            # 1. Media URLs (Aggressively stripped of slashes)
            video_match = re.search(r'class="EmbeddedMediaVideo"[^>]*src="([^"]+)"', html)
            if not video_match: video_match = re.search(r'"video_url":"(https:[^"]+)"', clean_html)
                
            image_match = re.search(r'class="EmbeddedMediaImage"[^>]*src="([^"]+)"', html)
            if not image_match: image_match = re.search(r'"display_url":"(https:[^"]+)"', clean_html)

            if video_match:
                video_url = video_match.group(1).replace("&amp;", "&").replace("\\/", "/").replace("\\\\/", "/")
            else:
                video_url = None

            if image_match:
                image_url = image_match.group(1).replace("&amp;", "&").replace("\\/", "/").replace("\\\\/", "/")
            else:
                image_url = None

            # 2. Author
            username_match = re.search(r'"owner":\{[^\}]*"username":"([^"]+)"', clean_html)
            if not username_match: username_match = re.search(r'class="UsernameText">([^<]+)<', html)
            author = username_match.group(1) if username_match else "unknown"

            # 3. Stats (Aggressive Search on cleaned HTML + Plain Text Fallback)
            def parse_text_number(text):
                text = text.upper().replace(',', '')
                if 'M' in text: return int(float(text.replace('M', '')) * 1000000)
                if 'K' in text: return int(float(text.replace('K', '')) * 1000)
                try: return int(float(text))
                except: return 0

            likes = 0
            comments = 0
            plays = 0
            
            # Try JSON fragments first
            like_m = re.search(r'"edge_media_preview_like":\{"count":(\d+)', clean_html) or re.search(r'"like_count":(\d+)', clean_html)
            if like_m: likes = int(like_m.group(1))

            comment_m = re.search(r'"edge_media_to_parent_comment":\{"count":(\d+)', clean_html) or re.search(r'"comment_count":(\d+)', clean_html)
            if comment_m: comments = int(comment_m.group(1))

            play_m = re.search(r'"video_view_count":(\d+)', clean_html) or re.search(r'"play_count":(\d+)', clean_html)
            if play_m: plays = int(play_m.group(1))

            # 🔥 NEW: Extract timestamp via Regex
            timestamp = None
            timestamp_m = re.search(r'"taken_at_timestamp":(\d+)', clean_html)
            if timestamp_m:
                timestamp = int(timestamp_m.group(1))
            else:
                # Fallback to the HTML datetime attribute if JSON fragment is missing
                time_m = re.search(r'datetime="([^"]+)"', html)
                if time_m:
                    timestamp = time_m.group(1) 

            # HAIL MARY: Plain text fallback
            if likes == 0:
                html_like_m = re.search(r'>([\d,KkMm.]+)\s+likes?<', html, re.IGNORECASE)
                if html_like_m: likes = parse_text_number(html_like_m.group(1))
                
            if comments == 0:
                # 🚀 Fix: Look for "View all X comments"
                html_comment_m = re.search(r'View\s+all\s+([\d,KkMm.]+)\s+comments?', html, re.IGNORECASE)
                if not html_comment_m:
                    html_comment_m = re.search(r'>([\d,KkMm.]+)\s+comments?<', html, re.IGNORECASE)
                if html_comment_m: comments = parse_text_number(html_comment_m.group(1))

            # 4. Collaborators & Tags
            collaborators = []
            tagged_users = []

            coauthor_block = re.search(r'"coauthor_producers":\[(.*?)\]', clean_html)
            if coauthor_block:
                collaborators = list(dict.fromkeys(re.findall(r'"username":"([^"]+)"', coauthor_block.group(1))))

            tagged_block = re.search(r'"edge_media_to_tagged_user":\{"edges":\[(.*?)\]\}', clean_html)
            if tagged_block:
                tagged_users = list(dict.fromkeys(re.findall(r'"username":"([^"]+)"', tagged_block.group(1))))

            if author not in collaborators and author != "unknown":
                collaborators.insert(0, author)

            # 5. Caption Extraction
            caption = ""
            caption_m = re.search(r'<div class="Caption"[^>]*>(.*?)</div>', html, re.DOTALL)
            if caption_m:
                caption = re.sub(r'<[^>]+>', '', caption_m.group(1)).strip()
            else:
                cap_json_m = re.search(r'"edge_media_to_caption":\{"edges":\[\{"node":\{"text":"(.*?)"\}\}\]\}', clean_html)
                if cap_json_m:
                    caption = cap_json_m.group(1)

            # 🚀 Clean "View all X comments" out of the caption so it looks professional
            caption = re.sub(r'View\s+all\s+[\d,KkMm.]+\s+comments?', '', caption, flags=re.IGNORECASE).strip()

            # 🚀 Clean the URLs with Heavy Artillery (nuke all backslashes before forward slashes)
            if video_url: video_url = re.sub(r'\\+/', '/', video_url)
            if image_url: image_url = re.sub(r'\\+/', '/', image_url)

            if not video_url and not image_url:
                log("❌ Could not find media URLs in Embed HTML. Layout may have changed.")
                return None

            return {
                "shortcode": shortcode,
                "type": "VIDEO" if video_url else "IMAGE",
                "video_url": video_url,
                "image_url": image_url,
                "author": author,
                "collaborators": collaborators,
                "tagged_users": tagged_users,
                "caption": caption,
                "likes": likes,
                "comments": comments,
                "plays": plays,
                "timestamp": timestamp # 🔥 ADDED THIS
            }

        except Exception as e:
            log(f"❌ Scraper Error: {str(e)}")
            return None

# ---------------- MAIN ---------------- #

async def main():
    if len(sys.argv) > 1:
        raw_input = sys.argv[1]
    else:
        raw_input = input("Enter IG Reel/Post URL or Shortcode: ")

    shortcode = extract_shortcode(raw_input)
    
    if not shortcode:
        log("❌ Could not extract shortcode from input.")
        sys.exit(1)

    result = await fetch_media_data_embed(shortcode)
    
    if result:
        print(json.dumps(result, indent=2))
    else:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())