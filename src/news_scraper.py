"""news_scraper.py: Contains logic for scraping news articles from an API like NewsAPI.
Calls the news API based on search terms from search_terms.json."""
"""news_scraper.py: Contains logic for scraping news articles from an API like NewsAPI.
Calls the news API based on search terms from search_terms.json."""

import os
import sys
import requests
from dotenv import load_dotenv
from .database import DatabaseManager, ArticleManager

# Load environment variables
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

class NewsScraper:
    """Handles scraping articles from the News API."""

    def __init__(self, db_manager, article_manager):
        load_dotenv()
        self.db_manager = db_manager
        self.article_manager = article_manager
        self.NEWS_API_KEY = os.getenv("NEWS_API_KEY")
        self.NEWS_API_URL = os.getenv("NEWS_API_URL")

        # Ensure API key and URL are loaded properly
        if not self.NEWS_API_KEY or not self.NEWS_API_URL:
            raise ValueError("NEWS_API_KEY and NEWS_API_URL must be set in your environment variables.")

    def fetch_articles_for_term(self, search_term):
        """Fetch articles for a given search term using the News API."""
        articles = []
        params = {
            "q": search_term,
            "apiKey": self.NEWS_API_KEY,  # Fix: use self to reference the instance variable
            "pageSize": 100,
            "page": 1
        }

        while True:
            try:
                response = requests.get(self.NEWS_API_URL, params=params)  # Fix: use self to reference the instance variable

                if response.status_code != 200:
                    print(f"Error fetching articles for '{search_term}': {response.status_code}")
                    break

                data = response.json()
                articles.extend(data.get("articles", []))

                # Check if there are more pages
                if len(data.get("articles", [])) < params["pageSize"]:
                    break
                else:
                    params["page"] += 1  # Move to the next page

            except requests.RequestException as e:
                print(f"Request exception occurred while fetching articles for '{search_term}': {e}")
                break

        return articles

    def scrape_articles(self):
        """Main function to fetch and store articles for each search term."""
        search_terms = self.db_manager.get_search_terms()

        if not search_terms:
            print("No search terms found to scrape articles.")
            return

        for term_id, search_term in search_terms:
            print(f"Scraping articles for search term: {search_term}")
            articles = self.fetch_articles_for_term(search_term)

            if not articles:
                print(f"No articles found for term '{search_term}'.")
                continue

            for article in articles:
                self.article_manager.insert_raw_article(
                    search_term_id=term_id,
                    title=article["title"],
                    content=article.get("content", ""),
                    source=article["source"]["name"] if article.get("source") else "",
                    url=article["url"],
                    url_to_image=article.get("urlToImage", ""),
                    published_at=article.get("publishedAt")
                )
            print(f"Stored {len(articles)} articles for term '{search_term}'.")

if __name__ == "__main__":
    # Initialize database manager and article manager
    db_manager = DatabaseManager()
    article_manager = ArticleManager(db_manager)

    # Initialize NewsScraper
    news_scraper = NewsScraper(db_manager, article_manager)

    # Refresh search terms and scrape articles
    db_manager.refresh_search_terms()
    news_scraper.scrape_articles()
