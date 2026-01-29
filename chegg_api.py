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

def safe_post(url: str, headers: Dict[str, str], payload: Dict[str, Any], proxy: str = None, files=None):
    proxies = None
    if proxy:
        proxies = {
            "http": proxy,
            "https": proxy
        }

    try:
        if files:
            # Let requests handle boundary
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
    if len(clean_text) > 400:
        clean_text = clean_text[:400]

    # 2. Ensure HTML wrapping
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

# --- FEATURE 2: POST THE QUESTION (TEXT) ---
def post_question_to_chegg(account_cookies_json, content, subject_title, subject_id, group_id, proxy=None):
    """Posts question to specific Subject/Group."""
    
    if "<" not in content:
        html_content = f"<div><p>{content}</p></div>"
    else:
        html_content = content

    print(f"   [API] Posting to: {subject_title} (ID: {subject_id}, Group: {group_id}) [Proxy: {proxy}]")
    
    cookie_header = parse_cookie_string(account_cookies_json)
    if not cookie_header:
        return False, "Invalid Cookie Data"

    headers = dict(BASE_HEADERS)
    headers["Cookie"] = cookie_header
    headers["x-chegg-referrer"] = "search?search=" + requests.utils.quote(html_content[:50])
    conversation_id = str(uuid.uuid4())
    headers["x-chegg-conversation-id"] = conversation_id

    # Step 1: Start
    print("   [API] Step 1: StartFollowUpConversation...")
    start_payload = {
        "operationName": "StartFollowUpConversation",
        "variables": {
            "conversationId": conversation_id,
            "interaction": {
                "data": {"sendToExpert": {"questionBody": html_content, "skipNBA": True}},
                "type": "SEND_TO_EXPERT",
                "plainText": "I'd like to ask an expert.",
            },
            "recommendedActions": ["SEND_TO_EXPERT"],
        },
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "90d3ad3c5581a08e6c8cd6e00e8f111857465d632d9a78bfecc6434d727d75d1"}}
    }
    
    status_sf, resp_sf = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=start_payload, proxy=proxy)
    if status_sf != 200:
        if isinstance(resp_sf, dict) and "errors" in resp_sf:
             return False, f"Start Failed: {resp_sf['errors'][0].get('message')}"
        return False, f"Start failed status {status_sf}"

    source_message_id = str(uuid.uuid4())
    try:
        source_message_id = resp_sf['data']['startFollowUpConversation']['interaction']['id']
    except:
        pass

    # Step 2: Continue (Confirm Subject)
    print("   [API] Step 2: ContinueConversation...")
    continue_payload = {
        "operationName": "ContinueConversation",
        "variables": {
            "conversationId": conversation_id,
            "message": {
                "content": {
                    "interaction": {
                        "data": {
                            "subjectConfirmation": {
                                "groupId": group_id,
                                "skipNBA": True,
                                "subjectId": subject_id,
                                "HTMLContent": html_content,
                                "isExpertQuestion": True,
                            }
                        },
                        "plainText": f"I need help with {subject_title}",
                        "type": "SUBJECT_CONFIRMATION",
                    }
                },
                "sourceMessageId": source_message_id,
            },
        },
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "d9f0a35cfdde80f9b010cc653734ff6d34f1fd7f72cc15847a1020d9e8b544a7"}}
    }
    
    status_cont, resp_cont = safe_post(ONE_GRAPH_ENDPOINT, headers=headers, payload=continue_payload, proxy=proxy)

    if status_cont == 200:
        if isinstance(resp_cont, dict) and "errors" in resp_cont:
             return False, f"Final Error: {resp_cont['errors'][0].get('message')}"
        print("   [API] SUCCESS! Question Posted.")
        return True, "Posted Successfully"
    else:
        return False, f"Final step failed status {status_cont}"

# --- FEATURE 3: IMAGE UPLOAD & OCR ---

def upload_image_to_chegg(cookie_json, image_path, proxy=None):
    """Uploads a local file to Chegg Media Proxy."""
    print(f"   [API] Uploading image: {image_path}...")
    
    headers = dict(BASE_HEADERS)
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
            # --- FIX FOR RESPONSE PARSING ---
            if 'result' in data:
                # Chegg can return 'uri', 'secureUri', or 'url' inside result
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

def post_question_v3(cookie_json, html_body, subject_id, proxy=None):
    """Posts question using V3 mutation (supports Image HTML)."""
    print(f"   [API] Posting V3 Question...")
    
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
            return False, data['errors'][0].get('message', 'Unknown V3 Error')
        return True, "Posted Successfully (V3)"
    return False, f"V3 Failed Status: {status}"
