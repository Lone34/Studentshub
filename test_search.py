from app import app, db
from models import Job, ServiceAccount
import requests
import urllib.parse
from bs4 import BeautifulSoup

def test_search():
    with app.app_context():
        # Get a stuck job
        job = Job.query.filter(Job.status == 'Completed', Job.chegg_link == None).order_by(Job.id.desc()).first()
        if not job:
            print("No stuck jobs to test with.")
            text = "The hardness of a material is generally defined as its resistance to"
        else:
            print(f"Testing with Job #{job.id}")
            # Use first 100 chars of content
            text = job.content[:100].replace('\n', ' ')
            
        print(f"Searching for: {text}")
        encoded_query = urllib.parse.quote_plus(text)
        
        url = f"https://www.chegg.com/search/{encoded_query}"
        
        # Get Proxy
        proxy = None
        if job and job.service_account_name:
             sa = ServiceAccount.query.filter_by(name=job.service_account_name).first()
             if sa and sa.proxy:
                 proxy = sa.proxy
                 print(f"Using Proxy: {proxy}")
        
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        try:
            resp = requests.get(url, headers=headers, proxies=proxies, timeout=15)
            print(f"Status: {resp.status_code}")
            
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if "/homework-help/questions-and-answers/" in href:
                        links.append(href)
                
                print(f"Found {len(links)} potential links.")
                for l in links[:3]:
                    print(f" - {l}")
            else:
                print("Search failed (Non-200).")
                
        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    test_search()
