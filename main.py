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

# --- Configuracion -----------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 60

# --- Utilidades ---------------------------------------------------------------

def load_sites(file_path="sites.txt"):
    """Lee la lista de sitios desde el archivo de texto."""
    if not os.path.exists(file_path):
        print(f"Error: No se encontro el archivo '{file_path}'.")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        sites = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return sites

def is_recent(publish_date, hours=24):
    """Verifica si un articulo fue publicado en las ultimas 'hours' horas."""
    if not publish_date:
        return False
    now = datetime.now(timezone.utc)
    if publish_date.tzinfo is None:
        publish_date = publish_date.replace(tzinfo=timezone.utc)
    diff = now - publish_date
    return diff <= timedelta(hours=hours)

def parse_date(date_string):
    """Intenta parsear una fecha desde un string con multiples formatos."""
    if not date_string:
        return None
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(date_string)
    except Exception:
        return None

# --- Metodo 1: RSS Feed (Preferido) ------------------------------------------

def discover_rss_feed(site_url):
    """Intenta descubrir el feed RSS de un sitio web."""
    headers = {"User-Agent": USER_AGENT}
    
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
            
        print(f"  -> RSS Feed detecto {len(feed.entries)} entradas.")
        
        for entry in feed.entries:
            pub_date = None
            for date_field in ['published', 'updated', 'created']:
                if hasattr(entry, date_field) and getattr(entry, date_field):
                    pub_date = parse_date(getattr(entry, date_field))
                    if pub_date:
                        break
            
            if not is_recent(pub_date, hours):
                continue
            
            title = entry.get('title', 'Sin titulo')
            link = entry.get('link', '')
            
            desc = ''
            if hasattr(entry, 'summary') and entry.summary:
                desc_soup = BeautifulSoup(entry.summary, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            elif hasattr(entry, 'description') and entry.description:
                desc_soup = BeautifulSoup(entry.description, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            
            if not desc:
                desc = "Sin descripcion disponible."
            
            # Extraer imagen del articulo
            image_url = ''
            if hasattr(entry, 'media_content') and entry.media_content:
                for media in entry.media_content:
                    if 'image' in media.get('type', '') or media.get('medium') == 'image':
                        image_url = media.get('url', '')
                        break
            if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get('url', '')
            if not image_url and hasattr(entry, 'enclosures') and entry.enclosures:
                for enc in entry.enclosures:
                    if 'image' in enc.get('type', ''):
                        image_url = enc.get('href', enc.get('url', ''))
                        break
            if not image_url and hasattr(entry, 'content') and entry.content:
                for c in entry.content:
                    img_tag = BeautifulSoup(c.get('value', ''), 'html.parser').find('img')
                    if img_tag and img_tag.get('src'):
                        image_url = img_tag['src']
                        break
            if not image_url and hasattr(entry, 'summary') and entry.summary:
                img_tag = BeautifulSoup(entry.summary, 'html.parser').find('img')
                if img_tag and img_tag.get('src'):
                    image_url = img_tag['src']
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

# --- Metodo 2: Scraping con newspaper3k (Fallback) ---------------------------

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
            print(f"  -> newspaper3k detecto {len(paper.articles)} articulos potenciales.")
            for article in paper.articles:
                try:
                    article.config = config
                    article.download()
                    article.parse()
                    
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
                            'description': desc or "Sin descripcion disponible.",
                            'publish_date': article.publish_date,
                            'image': article.top_image or ''
                        })
                except Exception:
                    continue
        else:
            print(f"  -> newspaper3k no detecto articulos, usando fallback manual...")
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
                
                print(f"  -> Fallback detecto {len(found_urls)} posibles URLs.")
                
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
                                'description': article.meta_description or "Sin descripcion disponible.",
                                'publish_date': article.publish_date,
                                'image': article.top_image or ''
                            })
                    except Exception:
                        continue
            except Exception as e:
                print(f"  -> Fallback fallo: {e}")
    except Exception as e:
        print(f"  -> Error en scraping: {e}")
    
    return articles

# --- Orquestador Principal ----------------------------------------------------

def extract_news(sites, hours=24):
    """Para cada sitio, intenta RSS primero, si no hay RSS usa scraping."""
    all_news = []
    
    for site_url in sites:
        print(f"\nAnalizando: {site_url}")
        
        feed_url = discover_rss_feed(site_url)
        
        if feed_url:
            print(f"  -> Feed RSS encontrado: {feed_url}")
            articles = extract_from_rss(site_url, feed_url, hours)
        else:
            print(f"  -> No se encontro RSS, usando scraping...")
            articles = extract_from_scraping(site_url, hours)
        
        print(f"  -> Extraidas {len(articles)} noticias validas (ultimas {hours}h).")
        all_news.extend(articles)
    
    return all_news

# --- Generador de Reporte HTML ------------------------------------------------

def generate_html_report(news_data):
    """Genera un reporte HTML premium responsive estilo app de noticias."""
    
    HERO_URL = "https://raw.githubusercontent.com/nicolas-wall/Casino_News_Scraper/main/assets/hero_banner.png"
    
    hora = datetime.now().hour
    if hora < 12:
        saludo = "Buenos dias, Nico"
        subtitulo = "Arrancamos el dia con las ultimas novedades de la industria."
    elif hora < 18:
        saludo = "Buenas tardes, Nico"
        subtitulo = "Aca tenes un resumen fresco de lo que paso hoy."
    else:
        saludo = "Buenas noches, Nico"
        subtitulo = "Antes de cerrar el dia, mira lo que paso en la industria."
    
    fecha_hoy = datetime.now().strftime("%A %d de %B, %Y").capitalize()
    total = len(news_data) if news_data else 0
    
    sites_with_news = {}
    if news_data:
        for item in news_data:
            domain = item['site'].split('//')[-1].split('/')[0]
            sites_with_news[domain] = sites_with_news.get(domain, 0) + 1
    
    # -------------------------------------------------------------------
    # Email-safe HTML: table-based layout, no CSS classes, inline styles
    # Responsive: 100% width container, cards scale naturally
    # Hero: table with background image (works in Gmail, Outlook)
    # -------------------------------------------------------------------
    
    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
</head>
<body style="font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background-color:#111111;margin:0;padding:0;color:#e5e5e5;-webkit-font-smoothing:antialiased;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#111111;">
        <tr><td align="center" style="padding:16px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;">

                <!-- Hero Banner -->
                <tr><td style="padding:0 0 24px 0;">
                    <table width="100%" cellpadding="0" cellspacing="0" style="border-radius:16px;overflow:hidden;background:#1a1a1a;">
                        <tr><td background="{HERO_URL}" style="background-image:url('{HERO_URL}');background-size:cover;background-position:center;height:200px;" valign="bottom">
                            <!--[if gte mso 9]>
                            <v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:680px;height:200px;">
                            <v:fill type="tile" src="{HERO_URL}" />
                            <v:textbox inset="0,0,0,0">
                            <![endif]-->
                            <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(180deg,rgba(0,0,0,0.1) 0%,rgba(0,0,0,0.85) 100%);">
                                <tr><td style="padding:80px 28px 24px 28px;" valign="bottom">
                                    <div style="font-size:34px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;margin-bottom:4px;line-height:1.1;">Casino <span style="color:#f59e0b;">News</span></div>
                                    <div style="font-size:14px;color:rgba(255,255,255,0.6);font-weight:500;">{fecha_hoy}</div>
                                </td></tr>
                            </table>
                            <!--[if gte mso 9]>
                            </v:textbox></v:rect>
                            <![endif]-->
                        </td></tr>
                    </table>
                </td></tr>

                <!-- Greeting -->
                <tr><td style="padding:0 4px 20px 4px;">
                    <div style="font-size:24px;font-weight:700;color:#fafafa;margin:0 0 8px 0;">Hola, Nico &#128075;</div>
                    <div style="font-size:15px;color:#a3a3a3;line-height:1.5;">{subtitulo}</div>
                </td></tr>
"""

    if not news_data:
        html_content += """
                <tr><td style="text-align:center;padding:60px 20px;">
                    <div style="font-size:48px;margin-bottom:16px;">&#128237;</div>
                    <div style="font-size:16px;color:#737373;line-height:1.6;">Hoy fue un dia tranquilo.<br>No se encontraron noticias nuevas en las ultimas 24 horas.</div>
                </td></tr>
"""
    else:
        html_content += f"""
                <!-- Stats -->
                <tr><td style="padding:0 0 24px 0;">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;">
                        <tr>
                            <td width="33%" style="text-align:center;padding:16px 8px;">
                                <div style="font-size:24px;font-weight:700;color:#f59e0b;">{total}</div>
                                <div style="font-size:11px;color:#737373;text-transform:uppercase;letter-spacing:1.2px;margin-top:3px;font-weight:600;">Noticias</div>
                            </td>
                            <td width="33%" style="text-align:center;padding:16px 8px;">
                                <div style="font-size:24px;font-weight:700;color:#a78bfa;">{len(sites_with_news)}</div>
                                <div style="font-size:11px;color:#737373;text-transform:uppercase;letter-spacing:1.2px;margin-top:3px;font-weight:600;">Fuentes</div>
                            </td>
                            <td width="33%" style="text-align:center;padding:16px 8px;">
                                <div style="font-size:24px;font-weight:700;color:#34d399;">24h</div>
                                <div style="font-size:11px;color:#737373;text-transform:uppercase;letter-spacing:1.2px;margin-top:3px;font-weight:600;">Ventana</div>
                            </td>
                        </tr>
                    </table>
                </td></tr>

                <!-- Section Title -->
                <tr><td style="padding:0 4px 16px 4px;">
                    <div style="font-size:20px;font-weight:700;color:#fafafa;">Ultimas noticias</div>
                </td></tr>

                <!-- 2 Column Grid -->
                <tr><td>
                    <table width="100%" cellpadding="0" cellspacing="0">
"""

        for i, item in enumerate(news_data):
            domain = item['site'].split('//')[-1].split('/')[0]
            desc = item.get('description') or ""
            if len(desc) > 140:
                desc = desc[:137] + "..."

            card_html = f"""
                        <td width="50%" style="vertical-align:top;padding:4px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-radius:12px;overflow:hidden;">
                                <tr><td style="padding:16px 16px 14px 16px;">
                                    <div style="font-size:11px;font-weight:600;color:#f59e0b;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">{domain}</div>
                                    <div style="font-size:15px;font-weight:600;color:#fafafa;line-height:1.4;margin-bottom:8px;"><a href="{item['url']}" target="_blank" style="color:#fafafa;text-decoration:none;">{item['title']}</a></div>
                                    <div style="font-size:13px;color:#a3a3a3;line-height:1.5;margin-bottom:10px;">{desc}</div>
                                    <a href="{item['url']}" target="_blank" style="font-size:12px;color:#f59e0b;font-weight:600;text-decoration:none;">Leer mas &#8594;</a>
                                </td></tr>
                            </table>
                        </td>
"""

            if i % 2 == 0:
                html_content += '                        <tr>\n'

            html_content += card_html

            if i % 2 == 1 or i == len(news_data) - 1:
                if i % 2 == 0 and i == len(news_data) - 1:
                    html_content += '                        <td width="50%" style="vertical-align:top;padding:4px;"></td>\n'
                html_content += '                        </tr>\n'

        html_content += """
                    </table>
                </td></tr>
"""

    html_content += f"""
                <!-- Footer -->
                <tr><td style="text-align:center;padding:32px 16px 16px;">
                    <div style="font-size:12px;color:#525252;line-height:1.6;"><span style="font-weight:700;color:#737373;">Casino News</span> &middot; Generado con &#10084;&#65039;</div>
                    <div style="font-size:11px;color:#404040;margin-top:8px;">Recibis este mail cada manana automaticamente.</div>
                </td></tr>

            </table>
        </td></tr>
    </table>
</body>
</html>"""

    return html_content

# --- Envio de Correo ----------------------------------------------------------

def send_email_report(html_content, recipient, smtp_user, smtp_pass):
    """Envia el correo electronico en formato HTML usando SMTP de Gmail."""
    if not recipient or not smtp_user or not smtp_pass:
        print("Error: Credenciales SMTP o correo destinatario faltantes en .env.")
        return False

    print(f"Enviando reporte a {recipient}...")

    msg = EmailMessage()
    msg['Subject'] = f"Casino News - Tu Resumen Diario - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = f"Casino News <{smtp_user}>"
    msg['To'] = recipient
    msg['Date'] = formatdate(localtime=True)

    msg.set_content("Tu cliente de correo no soporta HTML, por favor abrelo en uno compatible.")
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

# --- Main ---------------------------------------------------------------------

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

    print("\nIniciando extraccion de noticias...")
    news_data = extract_news(sites, hours=24)

    if not news_data:
        print("\nNo se encontraron noticias publicadas en las ultimas 24 horas.")

    print(f"\nExtraccion finalizada. Total de noticias recientes: {len(news_data)}")

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
