import os
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import newspaper
from newspaper import Article, ArticleException, Config
import requests
from bs4 import BeautifulSoup
import smtplib
from email.message import EmailMessage
from email.utils import formatdate

def load_sites(file_path="sites.txt"):
    """Lee la lista de sitios desde el archivo de texto."""
    if not os.path.exists(file_path):
        print(f"Error: No se encontró el archivo '{file_path}'.")
        return []
        
    with open(file_path, 'r', encoding='utf-8') as f:
        # Filtrar lineas vacías o comentarios
        sites = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return sites

def is_recent(publish_date, hours=24):
    """Verifica si un artículo fue publicado en las últimas 'hours' horas."""
    if not publish_date:
        # Si no detecta fecha, puede que nos perdamos la noticia o incluyamos muy viejas.
        # Por precaución para este script, si no hay fecha, no la incluimos (o la marcamos para revisión).
        # Aunque para evitar un correo gigante, mejor ignorarlas si no sabemos la fecha,
        # o asumimos que al estar en la página principal es reciente.
        # Vamos a asumir que es reciente si la acabamos de encontrar en la portada, 
        # pero es peligroso en newspaper3k porque agarra TODO el sitio.
        # Mejor devolver False si está estrictamente vacío, salvo que queramos ser laxos.
        return False
        
    # Asegurarnos de usar offsets (timezone aware)
    now = datetime.now(timezone.utc)
    
    # Si la fecha extraída no tiene timezone, la asumimos como local (o UTC)
    if publish_date.tzinfo is None:
        publish_date = publish_date.replace(tzinfo=timezone.utc)
        
    diff = now - publish_date
    return diff <= timedelta(hours=hours)

def extract_news(sites, hours=24):
    """Accede a cada sitio y extrae noticias recientes usando newspaper y un fallback."""
    all_news = []
    
    # Configurar newspaper con timeouts aumentados para no dejar afuera sitios lentos
    config = Config()
    config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    config.request_timeout = 60 # 60 segundos máximo por request
    config.memoize_articles = False
    
    for site_url in sites:
        print(f"Analizando: {site_url}")
        recent_articles_for_site = []
        
        try:
            # 1. Intentar con newspaper3k primero
            paper = newspaper.build(site_url, config=config, language='es')
            
            # Si el sitio bloqueó newspaper o falló su parsing general, la lista estará vacía
            if paper.articles:
                print(f"  -> newspaper3k detectó {len(paper.articles)} artículos potenciales.")
                for article in paper.articles:
                    try:
                        article.config = config
                        article.download()
                        article.parse()
                        
                        if is_recent(article.publish_date, hours):
                            # Evita usar nlp() si no lo necesitamos estrictamente para no ralentizar,
                            # o usamos un timeout en la vida real, pero nlp() aquí es local y rápido
                            # si el tokenizador ya está bajado.
                            try:
                                article.nlp() 
                                desc = article.summary if article.summary else article.meta_description
                            except Exception:
                                desc = article.meta_description
                                
                            recent_articles_for_site.append({
                                'site': site_url,
                                'title': article.title,
                                'url': article.url,
                                'description': desc,
                                'publish_date': article.publish_date
                            })
                    except Exception as e:
                        continue # Ignorar artículo que falla
            else:
                print(f"  -> newspaper3k no detectó artículos, usando fallback manual...")
                # 2. Fallback: Parsear manualmente con requests y bs4 si newspaper falla
                try:
                    headers = {'User-Agent': config.browser_user_agent}
                    response = requests.get(site_url, headers=headers, timeout=60)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # Buscar enlaces que comúnmente son artículos (esto es heurístico)
                    links = soup.find_all('a', href=True)
                    
                    found_urls = set()
                    for a in links:
                        href = a['href']
                        # Filtro heurístico básico de noticia (tiene fecha en la url o es lo bastante largo)
                        if len(href) > 30 and (href.count('-') > 3 or '/news/' in href or '/article/' in href):
                            if not href.startswith('http'):
                                # Arreglar enlaces relativos
                                base = site_url.rstrip('/')
                                href = f"{base}/{href.lstrip('/')}"
                            found_urls.add(href)
                            
                    print(f"  -> Fallback detectó {len(found_urls)} posibles URLs de artículos.")
                    
                    for url in list(found_urls): # Revisar todos los enlaces encontrados en el fallback
                        try:
                            # Parsear artículo individual con newspaper
                            article = Article(url, config=config)
                            article.download()
                            article.parse()
                            
                            if is_recent(article.publish_date, hours):
                                recent_articles_for_site.append({
                                    'site': site_url,
                                    'title': article.title,
                                    'url': article.url,
                                    'description': article.meta_description,
                                    'publish_date': article.publish_date
                                })
                        except Exception:
                            continue
                except Exception as eval_e:
                    print(f"  -> Fallback falló: {eval_e}")

            print(f"  -> Extraídas {len(recent_articles_for_site)} noticias válidas (últimas {hours}h).")
            all_news.extend(recent_articles_for_site)
            
        except Exception as e:
            print(f"Error procesando el sitio {site_url}: {e}")
            
    return all_news

def generate_html_report(news_data):
    """Genera un string con código HTML bonito para el correo."""
    
    # CSS minimalista y moderno
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
        # Agrupar por sitio o simplemente listar ordenado
        # Aquí listamos tal cual el orden de scraping
        for item in news_data:
            # Obtener el dominio base para mostrarlo de forma bonita
            domain = item['site'].split('//')[-1].split('/')[0]
            
            # Limpiar descripción (tomar solo un fragmento si es muy larga)
            desc = item['description']
            if len(desc) > 250:
                desc = desc[:247] + "..."
                
            html_content += f"""
                <div class="article">
                    <div class="source">{domain}</div>
                    <h2 class="title"><a href="{item['url']}" target="_blank">{item['title']}</a></h2>
                    <p class="description">{desc}</p>
                </div>
            """
            
    # Cerrar HTML
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
    
    # Para que los clientes de correo lo interpreten como HTML
    msg.set_content("Tu cliente de correo no soporta HTML, por favor ábrelo en uno compatible.")
    msg.add_alternative(html_content, subtype='html')
    
    try:
        # Configuración para Gmail (usar puerto 587 con STARTTLS)
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

def main():
    load_dotenv()
    
    # 1. Cargar sitios
    sites = load_sites("sites.txt")
    if not sites:
        print("No hay sitios para analizar. Saliendo.")
        return
        
    print(f"Se encontraron {len(sites)} sitios para analizar.")
    
    # IMPORTANTE: Para usar article.nlp() en newspaper3k
    # Es posible que se requiera descargar el corpus punkt de NLTK la primera vez.
    import nltk
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        nltk.download('punkt_tab', quiet=True)
    
    # 2. Extraer noticias (Últimas 24 horas)
    print("\nIniciando extracción de noticias...")
    news_data = extract_news(sites, hours=24)
    
    if not news_data:
        print("\nNo se encontraron noticias publicadas en las últimas 24 horas.")
        # Opcionalmente, igual enviamos el correo avisando que no hay noticias.
        # En este script enviaremos el correo igual.
        
    print(f"\nExtracción finalizada. Total de noticias recientes: {len(news_data)}")
    
    # 3. Generar el HTML
    print("\nGenerando reporte HTML...")
    html_report = generate_html_report(news_data)
    
    # Guardar localmente para debugging/verificación por si acaso
    with open("last_report.html", "w", encoding="utf-8") as f:
        f.write(html_report)
    print("Reporte HTML guardado localmente como 'last_report.html'.")
    
    # 4. Enviar por correo
    smtp_user = os.getenv("SMTP_EMAIL")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL")
    
    send_email_report(html_report, recipient, smtp_user, smtp_pass)

if __name__ == "__main__":
    main()
