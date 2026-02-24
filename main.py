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

# â”€â”€â”€ ConfiguraciÃ³n â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 60

# â”€â”€â”€ Utilidades â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_sites(file_path="sites.txt"):
    """Lee la lista de sitios desde el archivo de texto."""
    if not os.path.exists(file_path):
        print(f"Error: No se encontrÃ³ el archivo '{file_path}'.")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        sites = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return sites

def is_recent(publish_date, hours=24):
    """Verifica si un artÃ­culo fue publicado en las Ãºltimas 'hours' horas."""
    if not publish_date:
        return False
    now = datetime.now(timezone.utc)
    if publish_date.tzinfo is None:
        publish_date = publish_date.replace(tzinfo=timezone.utc)
    diff = now - publish_date
    return diff <= timedelta(hours=hours)

def parse_date(date_string):
    """Intenta parsear una fecha desde un string con mÃºltiples formatos."""
    if not date_string:
        return None
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(date_string)
    except Exception:
        return None

# â”€â”€â”€ MÃ©todo 1: RSS Feed (Preferido) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            
        print(f"  -> RSS Feed detectÃ³ {len(feed.entries)} entradas.")
        
        for entry in feed.entries:
            # Extraer fecha de publicaciÃ³n
            pub_date = None
            for date_field in ['published', 'updated', 'created']:
                if hasattr(entry, date_field) and getattr(entry, date_field):
                    pub_date = parse_date(getattr(entry, date_field))
                    if pub_date:
                        break
            
            if not is_recent(pub_date, hours):
                continue
            
            # Extraer tÃ­tulo y enlace
            title = entry.get('title', 'Sin tÃ­tulo')
            link = entry.get('link', '')
            
            # Extraer descripciÃ³n
            desc = ''
            if hasattr(entry, 'summary') and entry.summary:
                desc_soup = BeautifulSoup(entry.summary, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            elif hasattr(entry, 'description') and entry.description:
                desc_soup = BeautifulSoup(entry.description, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            
            if not desc:
                desc = "Sin descripciÃ³n disponible."
            
            # Extraer imagen del artÃ­culo
            image_url = ''
            # 1. media:content o media:thumbnail
            if hasattr(entry, 'media_content') and entry.media_content:
                for media in entry.media_content:
                    if 'image' in media.get('type', '') or media.get('medium') == 'image':
                        image_url = media.get('url', '')
                        break
            if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get('url', '')
            # 2. Enclosures
            if not image_url and hasattr(entry, 'enclosures') and entry.enclosures:
                for enc in entry.enclosures:
                    if 'image' in enc.get('type', ''):
                        image_url = enc.get('href', enc.get('url', ''))
                        break
            # 3. Imagen dentro del content HTML
            if not image_url and hasattr(entry, 'content') and entry.content:
                for c in entry.content:
                    img_tag = BeautifulSoup(c.get('value', ''), 'html.parser').find('img')
                    if img_tag and img_tag.get('src'):
                        image_url = img_tag['src']
                        break
            # 4. Imagen dentro del summary HTML
            if not image_url and hasattr(entry, 'summary') and entry.summary:
                img_tag = BeautifulSoup(entry.summary, 'html.parser').find('img')
                if img_tag and img_tag.get('src'):
                    image_url = img_tag['src']
            # 5. Fallback: Fetch og:image from the article URL
            if not image_url and link:
                try:
                    r_article = requests.get(link, headers=headers, timeout=10)
                    soup_og = BeautifulSoup(r_article.text, 'html.parser')
                    og_img = soup_og.find('meta', property='og:image')
                    if og_img and og_img.get('content'):
                        image_url = og_img['content']
                except Exception:
                    pass
            
            articles.append({
                'site': site_url,
                'title': title,
                'url': link,
                'description': desc,
                'publish_date': pub_date,
                'image': image_url
            })
    except Exception as e:
        print(f"  -> Error leyendo RSS: {e}")
    
    return articles

# â”€â”€â”€ MÃ©todo 2: Scraping con newspaper3k (Fallback) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            print(f"  -> newspaper3k detectÃ³ {len(paper.articles)} artÃ­culos potenciales.")
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
                            'description': desc or "Sin descripciÃ³n disponible.",
                            'publish_date': article.publish_date,
                            'image': article.top_image or ''
                        })
                except Exception:
                    continue
        else:
            print(f"  -> newspaper3k no detectÃ³ artÃ­culos, usando fallback manual...")
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
                
                print(f"  -> Fallback detectÃ³ {len(found_urls)} posibles URLs.")
                
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
                                'description': article.meta_description or "Sin descripciÃ³n disponible.",
                                'publish_date': article.publish_date,
                                'image': article.top_image or ''
                            })
                    except Exception:
                        continue
            except Exception as e:
                print(f"  -> Fallback fallÃ³: {e}")
    except Exception as e:
        print(f"  -> Error en scraping: {e}")
    
    return articles

# â”€â”€â”€ Orquestador Principal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            print(f"  -> No se encontrÃ³ RSS, usando scraping...")
            articles = extract_from_scraping(site_url, hours)
        
        print(f"  -> ExtraÃ­das {len(articles)} noticias vÃ¡lidas (Ãºltimas {hours}h).")
        all_news.extend(articles)
    
    return all_news

# â”€â”€â”€ Generador de Reporte HTML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_html_report(news_data):
    """Genera un string con cÃ³digo HTML premium estilo app de noticias."""
    
    HERO_URL = "https://raw.githubusercontent.com/nicolas-wall/Casino_News_Scraper/main/assets/hero_banner.png"
    
    hora = datetime.now().hour
    if hora < 12:
        saludo = "Buenos dÃ­as, Nico"
        subtitulo = "Arrancamos el dÃ­a con las Ãºltimas novedades de la industria."
    elif hora < 18:
        saludo = "Buenas tardes, Nico"
        subtitulo = "AcÃ¡ tenÃ©s un resumen fresco de lo que pasÃ³ hoy."
    else:
        saludo = "Buenas noches, Nico"
        subtitulo = "Antes de cerrar el dÃ­a, mirÃ¡ lo que pasÃ³ en la industria."
    
    fecha_hoy = datetime.now().strftime("%A %d de %B, %Y").capitalize()
    total = len(news_data) if news_data else 0
    
    sites_with_news = {}
    if news_data:
        for item in news_data:
            domain = item['site'].split('//')[-1].split('/')[0]
            sites_with_news[domain] = sites_with_news.get(domain, 0) + 1
    
    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
</head>
<body style="font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background-color:#111111;margin:0;padding:0;color:#e5e5e5;-webkit-font-smoothing:antialiased;">
    <div style="max-width:640px;margin:0 auto;padding:16px;">
        
        <!-- Hero Banner -->
        <div style="position:relative;border-radius:16px;overflow:hidden;margin-bottom:24px;height:200px;background:#1a1a1a;">
            <img src="{HERO_URL}" alt="" style="width:100%;height:100%;object-fit:cover;display:block;opacity:0.6;">
            <div style="position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(180deg,rgba(0,0,0,0.2) 0%,rgba(0,0,0,0.85) 100%);display:flex;flex-direction:column;justify-content:flex-end;padding:28px;">
                <div style="font-size:32px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;margin-bottom:4px;">Casino <span style="color:#f59e0b;">News</span></div>
                <div style="font-size:13px;color:rgba(255,255,255,0.6);font-weight:500;">{fecha_hoy}</div>
            </div>
        </div>
        
        <!-- Greeting -->
        <div style="padding:0 4px 20px 4px;">
            <h2 style="font-size:22px;font-weight:700;color:#fafafa;margin:0 0 6px 0;">&#x1F44B; {saludo}</h2>
            <p style="font-size:14px;color:#a3a3a3;line-height:1.5;margin:0;">{subtitulo}</p>
        </div>
"""
    
    if not news_data:
        html_content += """
        <div style="text-align:center;padding:60px 20px;">
            <div style="font-size:48px;margin-bottom:16px;">&#x1F4ED;</div>
            <p style="font-size:15px;color:#737373;line-height:1.6;">Hoy fue un d&iacute;a tranquilo.<br>No se encontraron noticias nuevas en las &uacute;ltimas 24 horas.</p>
        </div>
"""
    else:
        html_content += f"""
        <!-- Stats -->
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;margin-bottom:24px;">
            <tr>
                <td style="text-align:center;padding:14px 8px;">
                    <div style="font-size:22px;font-weight:700;color:#f59e0b;">{total}</div>
                    <div style="font-size:10px;color:#737373;text-transform:uppercase;letter-spacing:1.2px;margin-top:2px;font-weight:600;">Noticias</div>
                </td>
                <td style="text-align:center;padding:14px 8px;">
                    <div style="font-size:22px;font-weight:700;color:#a78bfa;">{len(sites_with_news)}</div>
                    <div style="font-size:10px;color:#737373;text-transform:uppercase;letter-spacing:1.2px;margin-top:2px;font-weight:600;">Fuentes</div>
                </td>
                <td style="text-align:center;padding:14px 8px;">
                    <div style="font-size:22px;font-weight:700;color:#34d399;">24h</div>
                    <div style="font-size:10px;color:#737373;text-transform:uppercase;letter-spacing:1.2px;margin-top:2px;font-weight:600;">Ventana</div>
                </td>
            </tr>
        </table>
        
        <div style="font-size:20px;font-weight:700;color:#fafafa;margin:4px 0 16px 4px;">&Uacute;ltimas noticias</div>
        
        <!-- 2 Column Grid -->
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px;">
"""
        
        for i, item in enumerate(news_data):
            domain = item['site'].split('//')[-1].split('/')[0]
            desc = item.get('description') or ""
            if len(desc) > 120:
                desc = desc[:117] + "..."
            
            image = item.get('image', '')
            
            if image:
                img_html = f'<img src="{image}" alt="" style="width:100%;height:130px;object-fit:cover;display:block;">'
            else:
                img_html = '<div style="width:100%;height:100px;background:linear-gradient(135deg,#262626 0%,#1a1a1a 100%);text-align:center;line-height:100px;font-size:28px;">&#x1F4F0;</div>'
            
            card_html = f"""
            <td style="width:50%;vertical-align:top;">
                <div style="background:#1a1a1a;border-radius:12px;overflow:hidden;margin-bottom:4px;">
                    <a href="{item['url']}" target="_blank" style="text-decoration:none;">{img_html}</a>
                    <div style="padding:12px 14px 14px;">
                        <div style="font-size:10px;font-weight:600;color:#a3a3a3;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px;">{domain}</div>
                        <div style="font-size:13px;font-weight:600;color:#fafafa;line-height:1.4;margin-bottom:6px;"><a href="{item['url']}" target="_blank" style="color:#fafafa;text-decoration:none;">{item['title']}</a></div>
                        <div style="font-size:11px;color:#737373;line-height:1.4;margin-bottom:8px;">{desc}</div>
                        <a href="{item['url']}" target="_blank" style="font-size:11px;color:#f59e0b;font-weight:600;text-decoration:none;">Leer m&aacute;s &#x2192;</a>
                    </div>
                </div>
            </td>
"""
            
            if i % 2 == 0:
                html_content += '            <tr>\n'
            
            html_content += card_html
            
            if i % 2 == 1 or i == len(news_data) - 1:
                if i % 2 == 0 and i == len(news_data) - 1:
                    html_content += '            <td style="width:50%;vertical-align:top;"></td>\n'
                html_content += '            </tr>\n'
        
        html_content += '        </table>\n'
    
    html_content += """
        <!-- Footer -->
        <div style="text-align:center;padding:28px 16px 16px;">
            <p style="font-size:12px;color:#525252;line-height:1.6;margin:0;"><span style="font-weight:700;color:#737373;">Casino News</span> &middot; Generado con &#x2764;&#xFE0F;</p>
            <p style="font-size:11px;color:#525252;margin-top:6px;">Recib&iacute;s este mail cada ma&ntilde;ana autom&aacute;ticamente.</p>
        </div>
    </div>
</body>
</html>"""
    
    return html_content

# â”€â”€â”€ EnvÃ­o de Correo â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def send_email_report(html_content, recipient, smtp_user, smtp_pass):
    """EnvÃ­a el correo electrÃ³nico en formato HTML usando SMTP de Gmail."""
    if not recipient or not smtp_user or not smtp_pass:
        print("Error: Credenciales SMTP u correo destinatario faltantes en .env.")
        return False
        
    print(f"Enviando reporte a {recipient}...")
    
    msg = EmailMessage()
    msg['Subject'] = f"Casino News Â· Tu Resumen Diario - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = f"Casino News <{smtp_user}>"
    msg['To'] = recipient
    msg['Date'] = formatdate(localtime=True)
    
    msg.set_content("Tu cliente de correo no soporta HTML, por favor Ã¡brelo en uno compatible.")
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

# â”€â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    
    print("\nIniciando extracciÃ³n de noticias...")
    news_data = extract_news(sites, hours=24)
    
    if not news_data:
        print("\nNo se encontraron noticias publicadas en las Ãºltimas 24 horas.")
        
    print(f"\nExtracciÃ³n finalizada. Total de noticias recientes: {len(news_data)}")
    
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
