import requests
from bs4 import BeautifulSoup
from newspaper import Article, Config
from datetime import datetime, timezone, timedelta

def test_fallback(site_url):
    config = Config()
    config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    config.request_timeout = 60
    
    headers = {'User-Agent': config.browser_user_agent}
    response = requests.get(site_url, headers=headers, timeout=60)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=True)
    
    found_urls = set()
    for a in links:
        href = a['href']
        if len(href) > 30 and (href.count('-') > 3 or '/news/' in href or '/article/' in href):
            if not href.startswith('http'):
                base = site_url.rstrip('/')
                href = f"{base}/{href.lstrip('/')}"
            found_urls.add(href)
            
    print(f"Fallback detectó {len(found_urls)} posibles URLs de artículos.")
    
    valid = 0
    now = datetime.now(timezone.utc)
    for url in list(found_urls)[:15]:
        try:
            article = Article(url, config=config)
            article.download()
            article.parse()
            pd = article.publish_date
            
            if pd:
                if pd.tzinfo is None:
                    pd = pd.replace(tzinfo=timezone.utc)
                diff = now - pd
                hours = diff.total_seconds() / 3600
                print(f"[{hours:.1f}h] {article.title} | {pd}")
                if hours <= 24:
                    valid += 1
            else:
                print(f"[NO DATE] {article.title} | {url}")
        except Exception as e:
            print(f"Error {url}: {e}")
            
    print(f"Validos (h<=24): {valid}")

test_fallback("https://cdcgaming.com/")
