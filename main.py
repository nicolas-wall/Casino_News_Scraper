import os
import time
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import feedparser
import requests
from bs4 import BeautifulSoup
from newspaper import Article, Config
import smtplib
from email.message import EmailMessage
from email.utils import formatdate

# ─── Configuración ───────────────────────────────────────────────────────────

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 60

# ─── Utilidades ──────────────────────────────────────────────────────────────

def load_sites(file_path="sites.txt"):
    """Lee la lista de sitios desde el archivo de texto."""
    if not os.path.exists(file_path):
        print(f"Error: No se encontró el archivo '{file_path}'.")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        sites = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return sites

def is_recent(publish_date, hours=24):
    """Verifica si un artículo fue publicado en las últimas 'hours' horas."""
    if not publish_date:
        return False
    now = datetime.now(timezone.utc)
    if publish_date.tzinfo is None:
        publish_date = publish_date.replace(tzinfo=timezone.utc)
    diff = now - publish_date
    return diff <= timedelta(hours=hours)

def parse_date(date_string):
    """Intenta parsear una fecha desde un string con múltiples formatos."""
    if not date_string:
        return None
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(date_string)
    except Exception:
        return None

# ─── Método 1: RSS Feed (Preferido) ─────────────────────────────────────────

def discover_rss_feed(site_url):
    """Intenta descubrir el feed RSS de un sitio web."""
    headers = {"User-Agent": USER_AGENT}
    
    # 1. Probar URLs comunes de feeds RSS
    base = site_url.rstrip('/')
    common_paths = ['/feed/', '/feed', '/rss/', '/rss', '/feed/rss/', '/atom.xml', '/rss.xml']
    
    for path in common_paths:
        feed_url = base + path
        try:
            r = requests.get(feed_url, headers=headers, timeout=10)
            if r.status_code == 200 and ('xml' in r.headers.get('Content-Type', '').lower() or '<rss' in r.text[:500].lower() or '<feed' in r.text[:500].lower()):
                return feed_url
        except Exception:
            continue
    
    # 2. Buscar en el HTML del sitio con la etiqueta <link type="application/rss+xml">
    try:
        r = requests.get(site_url, headers=headers, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.text, 'html.parser')
        link = soup.find('link', type='application/rss+xml')
        if link and link.get('href'):
            href = link['href']
            if not href.startswith('http'):
                href = base + '/' + href.lstrip('/')
            return href
        link = soup.find('link', type='application/atom+xml')
        if link and link.get('href'):
            href = link['href']
            if not href.startswith('http'):
                href = base + '/' + href.lstrip('/')
            return href
    except Exception:
        pass
    
    return None

def extract_from_rss(site_url, feed_url, hours=24):
    """Extrae noticias recientes desde un feed RSS."""
    articles = []
    headers = {"User-Agent": USER_AGENT}
    
    try:
        r = requests.get(feed_url, headers=headers, timeout=REQUEST_TIMEOUT)
        feed = feedparser.parse(r.content)
        
        if not feed.entries:
            return articles
            
        print(f"  -> RSS Feed detectó {len(feed.entries)} entradas.")
        
        for entry in feed.entries:
            # Extraer fecha de publicación
            pub_date = None
            for date_field in ['published', 'updated', 'created']:
                if hasattr(entry, date_field) and getattr(entry, date_field):
                    pub_date = parse_date(getattr(entry, date_field))
                    if pub_date:
                        break
            
            if not is_recent(pub_date, hours):
                continue
            
            # Extraer título y enlace
            title = entry.get('title', 'Sin título')
            link = entry.get('link', '')
            
            # Extraer descripción
            desc = ''
            if hasattr(entry, 'summary') and entry.summary:
                # Limpiar HTML de la descripción
                desc_soup = BeautifulSoup(entry.summary, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            elif hasattr(entry, 'description') and entry.description:
                desc_soup = BeautifulSoup(entry.description, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            
            if not desc:
                desc = "Sin descripción disponible."
            
            articles.append({
                'site': site_url,
                'title': title,
                'url': link,
                'description': desc,
                'publish_date': pub_date
            })
    except Exception as e:
        print(f"  -> Error leyendo RSS: {e}")
    
    return articles

# ─── Método 2: Scraping con newspaper3k (Fallback) ──────────────────────────

def extract_from_scraping(site_url, hours=24):
    """Extrae noticias usando newspaper3k y BeautifulSoup como fallback."""
    articles = []
    
    config = Config()
    config.browser_user_agent = USER_AGENT
    config.request_timeout = REQUEST_TIMEOUT
    config.memoize_articles = False
    
    try:
        import newspaper
        paper = newspaper.build(site_url, config=config, language='es')
        
        if paper.articles:
            print(f"  -> newspaper3k detectó {len(paper.articles)} artículos potenciales.")
            for article in paper.articles:
                try:
                    article.config = config
                    article.download()
                    article.parse()
                    
                    # Fallback manual para extraer fecha si newspaper3k falla
                    if not article.publish_date and article.html:
                        soup_article = BeautifulSoup(article.html, 'html.parser')
                        meta_date = soup_article.find('meta', property='article:published_time')
                        if meta_date and meta_date.get('content'):
                            article.publish_date = parse_date(meta_date['content'])
                    
                    if is_recent(article.publish_date, hours):
                        try:
                            article.nlp()
                            desc = article.summary if article.summary else article.meta_description
                        except Exception:
                            desc = article.meta_description
                        
                        articles.append({
                            'site': site_url,
                            'title': article.title,
                            'url': article.url,
                            'description': desc or "Sin descripción disponible.",
                            'publish_date': article.publish_date
                        })
                except Exception:
                    continue
        else:
            print(f"  -> newspaper3k no detectó artículos, usando fallback manual...")
            # Fallback con BeautifulSoup
            try:
                headers = {'User-Agent': USER_AGENT}
                response = requests.get(site_url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                links = soup.find_all('a', href=True)
                
                found_urls = set()
                domain = site_url.split('//')[-1].split('/')[0]
                for a in links:
                    href = a['href']
                    if len(href) > 25 and not any(skip in href.lower() for skip in ['/about', '/contact', '/privacy', '/terms', '/author', '/category', '/tag']):
                        if not href.startswith('http'):
                            base = site_url.rstrip('/')
                            href = f"{base}/{href.lstrip('/')}"
                        if domain in href:
                            found_urls.add(href)
                
                print(f"  -> Fallback detectó {len(found_urls)} posibles URLs.")
                
                for url in list(found_urls):
                    try:
                        article = Article(url, config=config)
                        article.download()
                        article.parse()
                        
                        if not article.publish_date and article.html:
                            soup_article = BeautifulSoup(article.html, 'html.parser')
                            meta_date = soup_article.find('meta', property='article:published_time')
                            if meta_date and meta_date.get('content'):
                                article.publish_date = parse_date(meta_date['content'])
                        
                        if is_recent(article.publish_date, hours):
                            articles.append({
                                'site': site_url,
                                'title': article.title,
                                'url': article.url,
                                'description': article.meta_description or "Sin descripción disponible.",
                                'publish_date': article.publish_date
                            })
                    except Exception:
                        continue
            except Exception as e:
                print(f"  -> Fallback falló: {e}")
    except Exception as e:
        print(f"  -> Error en scraping: {e}")
    
    return articles

# ─── Orquestador Principal ───────────────────────────────────────────────────

def extract_news(sites, hours=24):
    """Para cada sitio, intenta RSS primero, si no hay RSS usa scraping."""
    all_news = []
    
    for site_url in sites:
        print(f"\nAnalizando: {site_url}")
        
        # Paso 1: Intentar descubrir RSS
        feed_url = discover_rss_feed(site_url)
        
        if feed_url:
            print(f"  -> Feed RSS encontrado: {feed_url}")
            articles = extract_from_rss(site_url, feed_url, hours)
        else:
            print(f"  -> No se encontró RSS, usando scraping...")
            articles = extract_from_scraping(site_url, hours)
        
        print(f"  -> Extraídas {len(articles)} noticias válidas (últimas {hours}h).")
        all_news.extend(articles)
    
    return all_news

# ─── Generador de Reporte HTML ───────────────────────────────────────────────

def generate_html_report(news_data):
    """Genera un string con código HTML bonito para el correo."""
    
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; color: #333; }
            .container { max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
            .header { background-color: #2c3e50; color: #ffffff; padding: 25px 20px; text-align: center; }
            .header h1 { margin: 0; font-size: 24px; font-weight: 600; }
            .header p { margin: 10px 0 0 0; font-size: 14px; opacity: 0.8; }
            .content { padding: 30px 20px; }
            .article { margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 20px; }
            .article:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
            .source { display: inline-block; background-color: #e0e7ff; color: #3730a3; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
            .method { display: inline-block; background-color: #d1fae5; color: #065f46; padding: 2px 6px; border-radius: 3px; font-size: 10px; margin-left: 6px; }
            .title { margin: 0 0 10px 0; font-size: 18px; line-height: 1.4; color: #1f2937; }
            .title a { color: #2563eb; text-decoration: none; transition: color 0.2s; }
            .title a:hover { color: #1d4ed8; text-decoration: underline; }
            .description { font-size: 14px; color: #4b5563; line-height: 1.6; margin: 0; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;}
            .footer { background-color: #f8fafc; padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }
            .no-news { text-align: center; padding: 40px 20px; color: #64748b; font-style: italic; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Reporte Diario de Noticias</h1>
                <p>Las últimas 24 horas resumidas para ti</p>
            </div>
            <div class="content">
    """
    
    if not news_data:
        html_content += """
                <div class="no-news">
                    <p>No se encontraron noticias publicadas en las últimas 24 horas.</p>
                </div>
        """
    else:
        for item in news_data:
            domain = item['site'].split('//')[-1].split('/')[0]
            
            desc = item.get('description') or "Sin descripción disponible."
            if len(desc) > 250:
                desc = desc[:247] + "..."
                
            html_content += f"""
                <div class="article">
                    <div class="source">{domain}</div>
                    <h2 class="title"><a href="{item['url']}" target="_blank">{item['title']}</a></h2>
                    <p class="description">{desc}</p>
                </div>
            """
            
    fecha_hoy = datetime.now().strftime("%d de %B, %Y")
    html_content += f"""
            </div>
            <div class="footer">
                Generado automáticamente el {fecha_hoy} • Casino News Scraper
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_content

# ─── Envío de Correo ─────────────────────────────────────────────────────────

def send_email_report(html_content, recipient, smtp_user, smtp_pass):
    """Envía el correo electrónico en formato HTML usando SMTP de Gmail."""
    if not recipient or not smtp_user or not smtp_pass:
        print("Error: Credenciales SMTP u correo destinatario faltantes en .env.")
        return False
        
    print(f"Enviando reporte a {recipient}...")
    
    msg = EmailMessage()
    msg['Subject'] = f"Tu Resumen de Noticias Diario - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = f"News Scraper <{smtp_user}>"
    msg['To'] = recipient
    msg['Date'] = formatdate(localtime=True)
    
    msg.set_content("Tu cliente de correo no soporta HTML, por favor ábrelo en uno compatible.")
    msg.add_alternative(html_content, subtype='html')
    
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            print("Correo enviado exitosamente.")
            return True
    except Exception as e:
        print(f"Error enviando correo: {e}")
        return False

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    load_dotenv()
    
    sites = load_sites("sites.txt")
    if not sites:
        print("No hay sitios para analizar. Saliendo.")
        return
        
    print(f"Se encontraron {len(sites)} sitios para analizar.")
    
    import nltk
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        nltk.download('punkt_tab', quiet=True)
    
    print("\nIniciando extracción de noticias...")
    news_data = extract_news(sites, hours=24)
    
    if not news_data:
        print("\nNo se encontraron noticias publicadas en las últimas 24 horas.")
        
    print(f"\nExtracción finalizada. Total de noticias recientes: {len(news_data)}")
    
    print("\nGenerando reporte HTML...")
    html_report = generate_html_report(news_data)
    
    with open("last_report.html", "w", encoding="utf-8") as f:
        f.write(html_report)
    print("Reporte HTML guardado localmente como 'last_report.html'.")
    
    smtp_user = os.getenv("SMTP_EMAIL")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL")
    
    send_email_report(html_report, recipient, smtp_user, smtp_pass)

if __name__ == "__main__":
    main()
