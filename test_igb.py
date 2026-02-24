import newspaper
from newspaper import Config
config = Config()
config.browser_user_agent = "Mozilla/5.0"
config.request_timeout = 60
paper = newspaper.build("https://igamingbusiness.com/", config=config)
print(f"Detectados: {len(paper.articles)}")
for a in paper.articles[:30]:
    try:
        a.download()
        a.parse()
        print(f"[{a.publish_date}] {a.title} - {a.url}")
    except Exception as e:
        pass
