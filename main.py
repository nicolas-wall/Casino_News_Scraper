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
                desc_soup = BeautifulSoup(entry.summary, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            elif hasattr(entry, 'description') and entry.description:
                desc_soup = BeautifulSoup(entry.description, 'html.parser')
                desc = desc_soup.get_text(strip=True)
            
            if not desc:
                desc = "Sin descripción disponible."
            
            # Extraer imagen del artículo
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
            # 3. Imagen dentro del summary HTML
            if not image_url and hasattr(entry, 'summary') and entry.summary:
                img_tag = BeautifulSoup(entry.summary, 'html.parser').find('img')
                if img_tag and img_tag.get('src'):
                    image_url = img_tag['src']
            
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
                            'publish_date': article.publish_date,
                            'image': article.top_image or ''
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
                                'publish_date': article.publish_date,
                                'image': article.top_image or ''
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
    """Genera un string con código HTML premium estilo app de noticias."""
    
    # Determinar saludo según la hora
    hora = datetime.now().hour
    if hora < 12:
        saludo = "☀️ ¡Buenos días, Nico!"
        subtitulo = "Arrancamos el día con las últimas novedades de la industria."
    elif hora < 18:
        saludo = "👋 ¡Buenas tardes, Nico!"
        subtitulo = "Acá tenés un resumen fresco de lo que pasó hoy."
    else:
        saludo = "🌙 ¡Buenas noches, Nico!"
        subtitulo = "Antes de cerrar el día, mirá lo que pasó en la industria."
    
    fecha_hoy = datetime.now().strftime("%A %d de %B, %Y").capitalize()
    total = len(news_data) if news_data else 0
    
    # Agrupar noticias por dominio para el resumen
    sites_with_news = {}
    if news_data:
        for item in news_data:
            domain = item['site'].split('//')[-1].split('/')[0]
            sites_with_news[domain] = sites_with_news.get(domain, 0) + 1
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #0f172a; margin: 0; padding: 20px; color: #e2e8f0; }}
            .container {{ max-width: 620px; margin: 0 auto; }}
            
            /* Header / Greeting */
            .greeting {{ background: linear-gradient(135deg, #1e293b 0%, #334155 100%); border-radius: 16px; padding: 32px 28px; margin-bottom: 20px; }}
            .greeting h1 {{ margin: 0 0 8px 0; font-size: 26px; font-weight: 700; color: #f8fafc; }}
            .greeting .subtitle {{ margin: 0 0 16px 0; font-size: 15px; color: #94a3b8; line-height: 1.5; }}
            .greeting .date {{ font-size: 13px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; }}
            
            /* Stats bar */
            .stats {{ display: flex; background: #1e293b; border-radius: 12px; padding: 16px 20px; margin-bottom: 20px; gap: 20px; }}
            .stat {{ text-align: center; flex: 1; }}
            .stat-number {{ font-size: 24px; font-weight: 700; color: #38bdf8; }}
            .stat-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }}
            
            /* Article card */
            .card {{ background: #1e293b; border-radius: 12px; overflow: hidden; margin-bottom: 16px; transition: transform 0.2s; }}
            .card-image {{ width: 100%; height: 200px; object-fit: cover; display: block; }}
            .card-body {{ padding: 20px 22px; }}
            .card-source {{ display: inline-block; background: rgba(99, 102, 241, 0.15); color: #818cf8; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 12px; }}
            .card-title {{ margin: 0 0 10px 0; font-size: 18px; line-height: 1.4; font-weight: 600; }}
            .card-title a {{ color: #f1f5f9; text-decoration: none; }}
            .card-title a:hover {{ color: #38bdf8; }}
            .card-desc {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin: 0 0 14px 0; }}
            .card-cta {{ display: inline-block; color: #38bdf8; font-size: 13px; font-weight: 600; text-decoration: none; }}
            .card-cta:hover {{ color: #7dd3fc; }}
            
            /* No image card variant */
            .card-no-img .card-body {{ padding: 22px; }}
            .card-no-img .card-title {{ font-size: 16px; }}
            
            /* Footer */
            .footer {{ text-align: center; padding: 24px 20px; font-size: 12px; color: #475569; }}
            .footer a {{ color: #64748b; text-decoration: none; }}
            
            /* No news */
            .no-news {{ text-align: center; padding: 60px 20px; color: #64748b; }}
            .no-news-emoji {{ font-size: 48px; margin-bottom: 16px; }}
            .no-news p {{ font-size: 16px; line-height: 1.6; }}
            
            /* Divider */
            .section-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px; color: #475569; margin: 24px 0 16px 4px; font-weight: 600; }}
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Greeting -->
            <div class="greeting">
                <h1>{saludo}</h1>
                <p class="subtitle">{subtitulo}</p>
                <p class="date">📅 {fecha_hoy}</p>
            </div>
    """
    
    if not news_data:
        html_content += """
            <div class="no-news">
                <div class="no-news-emoji">📭</div>
                <p>Hoy fue un día tranquilo.<br>No se encontraron noticias nuevas en las últimas 24 horas.</p>
            </div>
        """
    else:
        # Stats bar
        html_content += f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="background: #1e293b; border-radius: 12px; margin-bottom: 20px;">
                <tr>
                    <td style="text-align: center; padding: 16px;">
                        <div style="font-size: 24px; font-weight: 700; color: #38bdf8;">{total}</div>
                        <div style="font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px;">Noticias</div>
                    </td>
                    <td style="text-align: center; padding: 16px;">
                        <div style="font-size: 24px; font-weight: 700; color: #a78bfa;">{len(sites_with_news)}</div>
                        <div style="font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px;">Fuentes</div>
                    </td>
                    <td style="text-align: center; padding: 16px;">
                        <div style="font-size: 24px; font-weight: 700; color: #34d399;">24h</div>
                        <div style="font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px;">Ventana</div>
                    </td>
                </tr>
            </table>
        """
        
        html_content += '<div class="section-label">📰 Últimas noticias</div>'
        
        for item in news_data:
            domain = item['site'].split('//')[-1].split('/')[0]
            
            desc = item.get('description') or "Sin descripción disponible."
            if len(desc) > 200:
                desc = desc[:197] + "..."
            
            image = item.get('image', '')
            
            if image:
                html_content += f"""
            <div class="card">
                <a href="{item['url']}" target="_blank"><img class="card-image" src="{image}" alt="" onerror="this.style.display='none'"></a>
                <div class="card-body">
                    <span class="card-source">{domain}</span>
                    <h2 class="card-title"><a href="{item['url']}" target="_blank">{item['title']}</a></h2>
                    <p class="card-desc">{desc}</p>
                    <a href="{item['url']}" target="_blank" class="card-cta">Leer artículo completo →</a>
                </div>
            </div>
                """
            else:
                html_content += f"""
            <div class="card card-no-img">
                <div class="card-body">
                    <span class="card-source">{domain}</span>
                    <h2 class="card-title"><a href="{item['url']}" target="_blank">{item['title']}</a></h2>
                    <p class="card-desc">{desc}</p>
                    <a href="{item['url']}" target="_blank" class="card-cta">Leer artículo completo →</a>
                </div>
            </div>
                """
    
    html_content += f"""
            <!-- Footer -->
            <div class="footer">
                <p>Generado con ❤️ por Casino News Scraper</p>
                <p style="margin-top: 8px; font-size: 11px;">Recibís este mail cada mañana automáticamente.<br>¿Querés agregar o sacar fuentes? Editá el archivo <code>sites.txt</code> en el repo.</p>
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
