# Casino & iGaming News Scraper 🎰🗞️

An automated Python tool designed to scrape the latest news articles (published within the last 24 hours) from a customized list of top Casino and iGaming industry news websites.

## What it does

- **Automated Scraping**: Visits a predefined list of URLs (configured in `sites.txt`).
- **Smart Extraction**: Uses `newspaper3k` and a custom BeautifulSoup fallback to detect and extract article titles, links, and brief descriptions.
- **Time Filtering**: Filters the articles to only include those published in the last 24 hours.
- **HTML Email Reports**: Generates a clean, responsive HTML report highlighting the web source, title, and a brief description of each news piece.
- **Automated Delivery**: The report is sent daily at 7:00 AM UTC via email, powered entirely by GitHub Actions, meaning zero local server maintenance is required.

## Configuration (GitHub Actions)

To run this automatically on your own GitHub repository, you need to configure the following **Repository Secrets** (Under `Settings` > `Secrets and variables` > `Actions`):

- `SMTP_EMAIL`: The Gmail address used to send the emails.
- `SMTP_PASSWORD`: A 16-character [Google App Password](https://myaccount.google.com/apppasswords) generated for the sender account.
- `RECIPIENT_EMAIL`: The email address where the daily report should be delivered.

## Local Development

If you wish to run the scraper locally:

1. Clone the repository.
2. Install the required dependencies: `pip install -r requirements.txt`
3. Create a `.env` file based on `.env.example` and add your email credentials.
4. Run the script: `python main.py`
