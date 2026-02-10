import json
import uuid
import requests
import time
import os
import re
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from models import db, User, Notification

# --- NOTIFICATION & CHECKER HELPERS ---

def notify_super_admin(message, link=None):
    """
    Helper function to send a notification specifically to the Owner (ID 1).
    """
    try:
        # We assume ID 1 is the "Main Main" admin/owner
        admin = User.query.get(1) 
        if admin:
            # Check if we recently sent this exact alert to avoid spamming 100 times
            exists = Notification.query.filter_by(
                user_id=admin.id, 
                message=message, 
                is_read=False
            ).first()
            
            if not exists:
                print(f"🚨 ALERTING ADMIN: {message}")
                notif = Notification(user_id=admin.id, message=message, link=link)
                db.session.add(notif)
                db.session.commit()
    except Exception as e:
        print(f"Failed to notify admin: {e}")

def check_if_solved(chegg_url):
    """
    REAL LOGIC: Checks Chegg for Solution, Unsolved status, or Captcha blocks.
    Returns: 'SOLVED', 'UNSOLVED', 'CAPTCHA', or 'ERROR'
    """
    # Use a real browser User-Agent to try and bypass simple blocks
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        print(f"🕵️ DEBUG: Checking URL: {chegg_url}")
        response = requests.get(chegg_url, headers=headers, timeout=15)
        print(f"🕵️ DEBUG: Status Code: {response.status_code}")
        
        page_text = response.text.lower()
        
        # --- 1. CAPTCHA DETECTION ---
        if response.status_code == 403 or \
           "captcha" in page_text or \
           "verify you are human" in page_text or \
           "access denied" in page_text:
            print(f"⚠️ DEBUG: Captcha detected!")
            return 'CAPTCHA'

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # --- 2. JSON-LD CHECK (Most Reliable) ---
        # Look for the structured data script
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script:
            try:
                data = json.loads(json_ld_script.string)
                # print(f"🕵️ DEBUG: Found JSON-LD") # Uncomment if needed
                
                # The JSON-LD usually defines a QAPage with a mainEntity of type Question
                question_data = data.get('mainEntity', {})
                if question_data.get('@type') == 'Question':
                    
                    # Check "answerCount"
                    answer_count = question_data.get('answerCount', 0)
                    if answer_count > 0:
                        print(f"✅ DEBUG: Solved (JSON-LD answerCount: {answer_count})")
                        return 'SOLVED'
                        
                    # Check "acceptedAnswer" object presence
                    if question_data.get('acceptedAnswer'):
                       print(f"✅ DEBUG: Solved (JSON-LD acceptedAnswer found)")
                       return 'SOLVED'
                       
                    # If we found the Question object but no answer indicators, it's Unsolved
                    print(f"⏳ DEBUG: Unsolved (JSON-LD present but no answer)")
                    return 'UNSOLVED'
                    
            except json.JSONDecodeError:
                print(f"❌ DEBUG: JSON-LD Decode Error")
                pass # Fallback to text search if JSON parsing fails

        # --- 3. TEXT FALLBACK ---
        if "this question hasn't been solved yet" in page_text or \
           "we don't have a solution for this question" in page_text:
            print(f"⏳ DEBUG: Unsolved (Text Match)")
            return 'UNSOLVED'

        if "expert answer" in page_text or "best answer" in page_text:
             # Verify it's not "Get an expert answer" (upsell)
             if "get an expert answer" not in page_text:
                 print(f"✅ DEBUG: Solved (Text Match: 'expert answer')")
                 return 'SOLVED'
             
        # If we are unsure, return Unsolved so we check again.
        print(f"⏳ DEBUG: Unsolved (Fallback - No positive match)")
        return 'UNSOLVED'

    except Exception as e:
        print(f"❌ Error checking Chegg: {e}")
        return 'ERROR'

# --- CONFIGURATION ---
ONE_GRAPH_ENDPOINT = "https://gateway.chegg.com/one-graph/graphql"
MEDIA_PROXY_ENDPOINT = "https://proxy.chegg.com/content/media"

BASE_HEADERS = {
    "authority": "gateway.chegg.com",
    "accept": "application/json",
    "accept-language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "apollographql-client-name": "chegg-web",
    "apollographql-client-version": "main-10f12231-1980489198",
    "authorization": "Basic TnNZS3dJMGxMdVhBQWQwenFTMHFlak5UVXAwb1l1WDY6R09JZVdFRnVvNndRRFZ4Ug==",
    "content-type": "application/json",
    "origin": "https://www.chegg.com",
    "referer": "https://www.chegg.com/",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
}

def parse_cookie_string(cookie_data):
    try:
        data = json.loads(cookie_data)
        if isinstance(data, dict) and "cookie" in data:
            return data["cookie"]
        if isinstance(data, list):
            parts = []
            for c in data:
                name = c.get("name") or c.get("Name")
                value = c.get("value") or c.get("Value")
                if name and value:
                    parts.append(f"{name}={value}")
            return "; ".join(parts)
    except:
        return cookie_data 
    return ""

# --- FEATURE 4: CHECK ACCOUNT BALANCE ---
def get_account_balance(cookie_json, proxy=None):
    """Checks the questions usage/limit for a specific account."""
    print(f"   [API] Checking balance...")
    
    headers = dict(BASE_HEADERS)
    cookie_str = parse_cookie_string(cookie_json)
    if cookie_str:
        headers["Cookie"] = cookie_str
        
    payload = {
        'operationName': 'ExpertQuestionsBalance',
        'variables': {},
        'extensions': {
            'persistedQuery': {
                'version': 1,
                'sha256Hash': '66db9216d692198c44ab926ba405f1bde02da688180f033478682a24f059a26f',
            },
        },
    }
    
    status, data = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=payload, proxy=proxy)
    
    if status == 200:
        try:
            # Check for the specific structure you provided
            # path: data -> balance -> chat -> chatStarts
            if 'data' in data and 'balance' in data['data']:
                chat_data = data['data']['balance'].get('chat', {}).get('chatStarts', {})
                
                # 'balance' here = Used count (per your observation)
                # 'limit' = Total limit
                used = chat_data.get('balance', 0)
                limit = chat_data.get('limit', 0)
                
                return {"used": used, "limit": limit}

            # Fallback for other account types (viewer -> expertQuestions)
            elif 'data' in data and 'viewer' in data['data']:
                 expert_data = data['data']['viewer'].get('expertQuestions')
                 if expert_data:
                     # For this old structure, 'balance' usually meant remaining
                     return {"remaining": expert_data.get('balance', 0)}
            
            return {"error": "Unknown Data Structure"}
            
        except Exception as e:
            return {"error": f"Parse Error: {e}"}
            
    return {"error": "Network Error"}
def safe_post(url: str, headers: Dict[str, str], payload: Dict[str, Any], proxy: str = None, files=None):
    proxies = None
    if proxy:
        proxies = {
            "http": proxy,
            "https": proxy
        }

    try:
        # If files are present, do not set content-type (requests handles boundaries)
        if files:
            if "content-type" in headers:
                del headers["content-type"]
            resp = requests.post(url, headers=headers, files=files, timeout=60, proxies=proxies)
        else:
            resp = requests.post(url, headers=headers, json=payload, timeout=30, proxies=proxies)
            
        if resp.status_code in [200, 201]:
            return resp.status_code, resp.json()
        return resp.status_code, resp.text
    except Exception as e:
        print(f"[API ERROR] Connection Failed (Proxy used: {proxy}): {e}")
        return None, str(e)

# --- FEATURE 1.5: GET MY QUESTIONS (Fallback) ---
def get_latest_question_url(cookie_json, proxy=None):
    """Fetches key details of the most recent question asked by the user."""
    print(f"   [API] Fetching 'My Questions' for fallback...")
    
    headers = dict(BASE_HEADERS)
    cookie_str = parse_cookie_string(cookie_json)
    if cookie_str: headers["Cookie"] = cookie_str
    
    # Using a common hash for 'MyQuestions' (or similar)
    # Often 'MyQuestionsQuery' or part of general viewer query
    # We will try a known query hash
    payload = {
        'operationName': 'MyQuestions',
        'variables': {'limit': 1, 'offset': 0},
        'extensions': {
            'persistedQuery': {
                'version': 1,
                'sha256Hash': '9d7d9b7367803737300f892a0e5b018591873323058a56209b5522524a87754f' 
            }
        }
    }
    
    try:
        status, data = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=payload, proxy=proxy)
        
        if status == 200 and 'data' in data:
             # Structure: data -> myQuestions -> edges -> node -> slug, uuid
             items = data.get('data', {}).get('myQuestions', {}).get('edges', [])
             if items:
                 node = items[0].get('node', {})
                 slug = node.get('slug')
                 uuid = node.get('uuid')
                 if slug and uuid:
                     return f"https://www.chegg.com/homework-help/questions-and-answers/{slug}-{uuid}"
                     
    except Exception as e:
        print(f"   [API] MyQuestion Query failed: {e}")
        
    # --- SCRAPING FALLBACK ---
    try:
        print("   [API] Trying HTML Scraping for My Questions...")
        url = "https://www.chegg.com/my/questions-and-answers"
        resp = requests.get(url, headers=headers, proxies={"https": proxy} if proxy else None, timeout=15)
        
        if resp.status_code == 200:
            # Regex to find question links
            # Pattern: /homework-help/questions-and-answers/[slug]-[uuid]
            # or q[digits]
            
            # Look for the characteristic Q&A link pattern
            # We want the most recent one, which usually appears first in the source if it's a list
            import re
            matches = re.findall(r'href=["\'](https://www.chegg.com/homework-help/questions-and-answers/[^"\']+)["\']', resp.text)
            
            if matches:
                # Filter out likely junk/nav links if any (though the pattern is specific)
                # Return the first one
                print(f"   [API] Scraped URL: {matches[0]}")
                return matches[0]
                
            # Try relative path
            matches_rel = re.findall(r'href=["\'](/homework-help/questions-and-answers/[^"\']+)["\']', resp.text)
            if matches_rel:
                print(f"   [API] Scraped Relative URL: {matches_rel[0]}")
                return f"https://www.chegg.com{matches_rel[0]}"
            
            # If we are here, no matches found
            print(f"   [API] No matches found in {len(resp.text)} bytes.")
            try:
                 with open("scrape_dump.html", "w", encoding="utf-8") as f:
                     f.write(resp.text)
                 print("   [API] Dumped HTML to scrape_dump.html")
            except: pass
            
        else:
            print(f"   [API] My Questions Status Code: {resp.status_code}")
            try:
                 with open("scrape_dump_error.html", "w", encoding="utf-8") as f:
                     f.write(resp.text)
            except: pass
                
    except Exception as e:
        print(f"   [API] Scraping failed: {e}")
        try:
             with open("scrape_dump.html", "w", encoding="utf-8") as f:
                 f.write(resp.text)
             print("   [API] Dumped HTML to scrape_dump.html")
        except: pass

    return None

# --- FEATURE 1: FIND SUBJECTS FROM QUESTION TEXT ---
def get_subjects_from_text(cookie_json, question_text, proxy=None):
    """Sends question to Chegg to get valid subjects/IDs."""
    
    # 1. Clean and truncate text to avoid payload errors
    clean_text = re.sub(r'\s+', ' ', question_text).strip()
    # Chegg's subject predictor works best with a concise snippet
    if len(clean_text) > 400:
        clean_text = clean_text[:400]

    # 2. Ensure HTML wrapping for the search query
    if "<" not in clean_text:
        search_content = f"<div><p>{clean_text}</p></div>"
    else:
        search_content = clean_text

    print(f"   [API] Searching subjects for: {clean_text[:30]}... [Proxy: {proxy}]")
    
    headers = dict(BASE_HEADERS)
    cookie_str = parse_cookie_string(cookie_json)
    if cookie_str:
        headers["Cookie"] = cookie_str
    
    payload = {
        "operationName": "SubjectsByText",
        "variables": {"htmlContent": search_content},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "75e1ee626abccc167c92ed441082be2f55b3beb4a629594118d6fd952dabb568"}}
    }
    
    try:
        status, data = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=payload, proxy=proxy)
        
        # Check for GraphQL specific errors
        if isinstance(data, dict) and 'errors' in data:
            print(f"   [API] Subject Search GraphQL Error: {data['errors']}")
            return []

        results = []
        def collect_subjects(obj):
            if isinstance(obj, dict):
                if ("subjectId" in obj or "id" in obj) and ("title" in obj or "name" in obj):
                    title = obj.get("title") or obj.get("name")
                    sid = obj.get("subjectId") or obj.get("id")
                    gid = obj.get("groupId", 0)
                    if title and sid:
                        results.append({"title": title, "subjectId": sid, "groupId": gid})
                for v in obj.values():
                    collect_subjects(v)
            elif isinstance(obj, list):
                for item in obj:
                    collect_subjects(item)
                    
        collect_subjects(data)
        
        seen = set()
        unique_results = []
        for r in results:
            key = f"{r['title']}-{r['subjectId']}"
            if key not in seen:
                seen.add(key)
                unique_results.append(r)
        
        print(f"   [API] Found {len(unique_results)} subjects.")
        return unique_results[:25]
    except Exception as e:
        print(f"   [API] Search Error: {e}")
        return []

# --- FEATURE 2: POST THE QUESTION (UNIFIED V3 LOGIC) ---

def post_question_v3(cookie_json, html_body, subject_id, proxy=None):
    """
    Posts a question using the robust V3 mutation.
    This is a SINGLE atomic request, preventing double-posting issues.
    """
    print(f"   [API] Posting Question (V3 Mutation)...")
    
    headers = dict(BASE_HEADERS)
    cookie_str = parse_cookie_string(cookie_json)
    if cookie_str: headers["Cookie"] = cookie_str
    
    payload = {
        'operationName': 'postQuestionV3',
        'variables': {
            'body': html_body,
            'toExpert': True,
            'subjectId': subject_id,
        },
        'extensions': {
            'persistedQuery': {
                'version': 1,
                'sha256Hash': '6b55a6da8e693d68e3c64ebef994bafdf1db65eedfaae79ac8556b188c033c63',
            },
        },
    }
    
    status, data = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=payload, proxy=proxy)
    
    if status == 200:
        if "errors" in data:
            # Handle Chegg-specific errors (e.g., limit reached)
            return False, f"Chegg Error: {data['errors'][0].get('message', 'Unknown')}"
            
        # Extract URL if possible
        # Structure: data -> postQuestionV3 -> question -> link/url/slug ??
        try:
            res = data.get('data', {}).get('postQuestionV3', {})
            question = res.get('question', {})
            
            # 1. Direct Extraction
            if 'slug' in question and 'uuid' in question:
                url = f"https://www.chegg.com/homework-help/questions-and-answers/{question['slug']}-{question['uuid']}"
                return True, url
            elif 'url' in question:
                 return True, question['url']
                 
            # 2. Fallback: Fetch "My Questions" to get the latest one
            print(f"   [API] Direct URL missing, trying fallback (My Questions)...")
            time.sleep(2) # Wait a moment for indexing
            latest_url = get_latest_question_url(cookie_json, proxy)
            if latest_url:
                print(f"   [API] Fallback Success! URL: {latest_url}")
                return True, latest_url
                
        except Exception as e:
             print(f"   [API] URL Extraction Error: {e}")
            
        # Final Fallback
        return True, "Posted Successfully (Link not found in response)"
    return False, f"Network Error: {status}"

def post_question_to_chegg(account_cookies_json, content, subject_title, subject_id, group_id, proxy=None):
    """
    Wrapper for Text-Only questions.
    FIXED: Now uses post_question_v3 internally instead of the old 2-step process.
    This fixes the 'double question' bug.
    """
    # 1. Wrap raw text in HTML div/p tags if not already present
    if "<" not in content:
        html_body = f"<div><p>{content}</p></div>"
    else:
        html_body = content
        
    # 2. Call the reliable V3 function (ignoring group_id/title as V3 doesn't need them)
    return post_question_v3(account_cookies_json, html_body, subject_id, proxy)

# --- FEATURE 3: IMAGE UPLOAD & OCR ---

def upload_image_to_chegg(cookie_json, image_path, proxy=None):
    """Uploads a local file to Chegg Media Proxy."""
    print(f"   [API] Uploading image: {image_path}...")
    
    headers = dict(BASE_HEADERS)
    # Remove content-type so requests sets boundary for multipart
    if "content-type" in headers: del headers["content-type"]
    
    cookie_str = parse_cookie_string(cookie_json)
    if cookie_str: headers["Cookie"] = cookie_str

    try:
        mime_type = 'image/jpeg' if image_path.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
        filename = os.path.basename(image_path)

        with open(image_path, 'rb') as f:
            files = {
                'file': (filename, f, mime_type),
                'clientId': (None, 'STUDY'),
                'autoOrient': (None, 'false'),
            }
            
            proxies = {"https": proxy} if proxy else None
            resp = requests.post(MEDIA_PROXY_ENDPOINT, headers=headers, files=files, proxies=proxies, timeout=60)
            
        if resp.status_code in [200, 201]:
            data = resp.json()
            # Extract URL/URI safely (handling different Chegg response formats)
            if 'result' in data:
                if 'uri' in data['result']:
                    return data['result']['uri']
                elif 'secureUri' in data['result']:
                    return data['result']['secureUri']
                elif 'url' in data['result']:
                    return data['result']['url']
            
            if 'url' in data:
                return data['url']
            
            print(f"   [API] URL/URI not found in response: {data}")
            return None
        else:
            print(f"   [API] Upload Failed: {resp.text}")
            return None
    except Exception as e:
        print(f"   [API] Upload Error: {e}")
        return None

def ocr_analyze_image(cookie_json, image_url, proxy=None):
    """Analyzes the uploaded image URL to get text."""
    print(f"   [API] OCR Analysis for: {image_url[:40]}...")
    
    headers = dict(BASE_HEADERS)
    cookie_str = parse_cookie_string(cookie_json)
    if cookie_str: headers["Cookie"] = cookie_str
    
    payload = {
        'operationName': 'OCRAnalyze',
        'variables': {'imageUrl': image_url},
        'query': 'query OCRAnalyze($imageUrl: String!) {\n  ocrAnalyze(imageUrl: $imageUrl) {\n    transcriptionText\n    transcriptionHtml\n    confidence\n    hasTable\n    hasDiagram\n    __typename\n  }\n}\n',
    }
    
    status, data = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=payload, proxy=proxy)
    
    if status == 200 and 'data' in data and 'ocrAnalyze' in data['data']:
        return data['data']['ocrAnalyze'].get('transcriptionText', '')
    return ""
