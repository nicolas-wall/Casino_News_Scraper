import newspaper
from newspaper import Config
config = Config()
config.browser_user_agent = "Mozilla/5.0"
config.request_timeout = 60
paper = newspaper.build("https://cdcgaming.com/", config=config)
print(f"Detectados: {len(paper.articles)}")
missing_date = 0
for a in paper.articles[:20]:
    try:
        a.download()
        a.parse()
        if not a.publish_date:
            missing_date += 1
            print(f"Missing Date -> Title: {a.title} | URL: {a.url}")
        else:
            print(f"Has Date -> Title: {a.title} | Date: {a.publish_date}")
    except Exception as e:
        print(f"Error: {e}")
print(f"Missing Date count: {missing_date}")
