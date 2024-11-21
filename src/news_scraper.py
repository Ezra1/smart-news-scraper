"""news_scraper.py: Contains logic for scraping news articles from NewsAPI.
Calls the news API based on search terms from search_terms.json."""

import os
import sys
import requests
import logging
import logging.config
from dotenv import load_dotenv
from .database import DatabaseManager, ArticleManager, SearchTermManager

# Get the absolute path to the logging.conf file
current_directory = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')

# Set up logging
logging.config.fileConfig(logging_config_path)
logger = logging.getLogger(__name__)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

class NewsScraper:
    """Handles scraping articles from the News API."""

    def __init__(self, db_manager):
        load_dotenv()
        self.db_manager = db_manager  # Use the passed in db_manager
        self.article_manager = ArticleManager(db_manager)  # Initialize article_manager
        self.search_term_manager = SearchTermManager(db_manager)
        self.NEWS_API_KEY = os.getenv("NEWS_API_KEY")
        self.NEWS_API_URL = os.getenv("NEWS_API_URL")
    
        if not self.NEWS_API_KEY or not self.NEWS_API_URL:
            logging.error("NEWS_API_KEY and NEWS_API_URL must be set in your environment variables.")
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
                    logging.error(f"Error fetching articles for '{search_term}': {response.status_code}")
                    break

                data = response.json()
                articles.extend(data.get("articles", []))

                # Check if there are more pages
                if len(data.get("articles", [])) < params["pageSize"]:
                    break
                else:
                    params["page"] += 1  # Move to the next page

            except requests.RequestException as e:
                logging.error(f"Request exception occurred while fetching articles for '{search_term}': {e}")
                break

        return articles

    def scrape_articles(self):
        """Main function to fetch and store articles for each search term."""
        search_terms = self.search_term_manager.get_search_terms() 
    
        if not search_terms:
            logging.error("No search terms found to scrape articles.")
            return
    
        for term in search_terms:
            term_id = term['id']
            search_term = term['term']
            logging.info(f"Scraping articles for search term: {search_term}")

if __name__ == "__main__":
    # Initialize NewsScraper
    db_manager = DatabaseManager()
    article_manager = ArticleManager(db_manager)
    news_scraper = NewsScraper(db_manager, article_manager)
    news_scraper.scrape_articles()