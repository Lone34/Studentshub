import json
import uuid
import requests
import time
import os
import re
from typing import Dict, Any, List

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
        return True, "Posted Successfully"
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
