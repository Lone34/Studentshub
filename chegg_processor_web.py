import requests
import json
import re
import logging
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

class CheggProcessorWeb:
    def __init__(self):
        self.base_url = "https://gateway.chegg.com/one-graph/graphql"
        self.base_headers = {
            'authority': 'gateway.chegg.com',
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'apollographql-client-name': 'chegg-web',
            'apollographql-client-version': 'main-2025-latest',
            'authorization': 'Basic TnNZS3dJMGxMdVhBQWQzenFTMHFlak5UVXAwb1l1WDY6R09JZVdFRnVvNndRRFZ4Ug==',
            'content-type': 'application/json',
            'origin': 'https://www.chegg.com',
            'referer': 'https://www.chegg.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }

    def _get_session(self, cookie_data, proxy=None):
        """Creates a session with the specific account credentials."""
        session = requests.Session()
        
        # Parse cookie string/JSON
        cookie_str = ""
        try:
            if isinstance(cookie_data, str) and (cookie_data.strip().startswith('{') or cookie_data.strip().startswith('[')):
                cookie_json = json.loads(cookie_data)
                if isinstance(cookie_json, list):
                    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookie_json])
                elif isinstance(cookie_json, dict) and 'cookie' in cookie_json:
                    cookie_str = cookie_json['cookie']
            else:
                cookie_str = cookie_data
        except:
            cookie_str = cookie_data

        headers = self.base_headers.copy()
        headers['Cookie'] = cookie_str
        session.headers.update(headers)

        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
            
        return session

    def extract_uuid_from_url(self, url):
        """Extracts UUID or ID from URL."""
        url = url.split('?')[0].strip()
        
        # Regex for UUID
        uuid_match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', url, re.IGNORECASE)
        if uuid_match:
            return uuid_match.group(1)
            
        # Regex for old numerical ID
        id_match = re.search(r'q(\d+)', url, re.IGNORECASE)
        if id_match:
            return id_match.group(1)
            
        return None

    def get_question_data(self, url, cookie_data, proxy=None):
        """Main entry point to fetch question data."""
        session = self._get_session(cookie_data, proxy)
        question_id = self.extract_uuid_from_url(url)
        
        if not question_id:
            return None, "Invalid URL format."

        # 1. Handle Legacy IDs (Numeric)
        if question_id.isdigit():
            print(f"DEBUG: Processing Legacy ID: {question_id}")
            
            # Method A: Try API Conversion (Often fails now)
            payload = {
                'operationName': 'QnaPageAnswerSub',
                'variables': {'id': int(question_id)},
                'query': 'query QnaPageAnswerSub($id: Int!) { questionByLegacyId(id: $id) { uuid } }'
            }
            try:
                resp = session.post(self.base_url, json=payload, timeout=10)
                data = resp.json()
                new_uuid = data.get('data', {}).get('questionByLegacyId', {}).get('uuid')
                
                if new_uuid:
                    print(f"DEBUG: API Conversion Success -> {new_uuid}")
                    question_id = new_uuid
                else:
                    # Method B: Scrape Page for UUID (Robust Fallback)
                    print("DEBUG: API Conversion failed. Scraping page source...")
                    page_headers = session.headers.copy()
                    page_headers['Accept'] = 'text/html,application/xhtml+xml'
                    page_resp = session.get(url, headers=page_headers, timeout=15)
                    
                    # Search for UUID in page source
                    # Common patterns in Chegg source
                    patterns = [
                        r'"uuid":"([0-9a-f-]{36})"',
                        r'data-uuid="([0-9a-f-]{36})"',
                        r'questionId":"([0-9a-f-]{36})"'
                    ]
                    
                    found_uuid = None
                    for p in patterns:
                        match = re.search(p, page_resp.text)
                        if match:
                            found_uuid = match.group(1)
                            break
                    
                    if found_uuid:
                        print(f"DEBUG: Scrape Success -> {found_uuid}")
                        question_id = found_uuid
                    else:
                        return None, "Could not resolve Legacy ID to UUID (Page Scrape failed)."

            except Exception as e:
                return None, f"Legacy ID Resolution Error: {str(e)}"

        # 2. Fetch Question Data (Using NEW Hashes)
        print(f"DEBUG: Fetching content for UUID: {question_id}")
        
        # ATTEMPT 1: QnaById (New Hash)
        payload_primary = {
            'operationName': 'QnaById',
            'variables': {'id': question_id},
            'extensions': {
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': 'bb6c7023b5bfb7b147725978ec7de015ae02d4de62ac8e17490782af338ce884'
                }
            }
        }
        
        try:
            resp = session.post(self.base_url, json=payload_primary, timeout=15)
            
            if resp.status_code == 401:
                return None, "Account Cookie Expired"
            if resp.status_code == 403:
                return None, "Account Blocked (Captcha)"
                
            data = resp.json()
            q_data = data.get('data', {}).get('questionByUuid', {})

            # ATTEMPT 2: QuestionByUuidAuthorId (New Hash - Fallback)
            if not q_data:
                print("DEBUG: Primary query empty, trying Fallback (AuthorId)...")
                payload_secondary = {
                    'operationName': 'QuestionByUuidAuthorId',
                    'variables': {'uuid': question_id},
                    'extensions': {
                        'persistedQuery': {
                            'version': 1,
                            'sha256Hash': '39ebccbc7a097b645d1f47f2ca46c3eaf7e472613cbefbc8766fe400500af15a'
                        }
                    }
                }
                resp_sec = session.post(self.base_url, json=payload_secondary, timeout=15)
                data_sec = resp_sec.json()
                q_data = data_sec.get('data', {}).get('questionByUuid', {})

            # Final Check
            if not q_data:
                if 'errors' in data:
                    return None, f"Chegg API Error: {data['errors'][0].get('message')}"
                return None, "Question data not found (Wait or check URL)."
            
            return {
                'question_id': question_id,
                'question_data': q_data,
                'html_link': url
            }, None
            
        except Exception as e:
            return None, f"API Request Error: {str(e)}"

chegg_processor = CheggProcessorWeb()
