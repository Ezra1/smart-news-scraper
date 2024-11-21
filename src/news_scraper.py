"""src/news_scraper.py"""

import os
import sys
import requests
import logging
import logging.config
import time
from datetime import datetime, timedelta
from typing import Dict, List
from dotenv import load_dotenv
from ratelimit import limits, sleep_and_retry
from .database import DatabaseManager, ArticleManager, SearchTermManager

# Get the absolute path to the logging.conf file
current_directory = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')

# Set up logging
logging.config.fileConfig(logging_config_path)
logger = logging.getLogger(__name__)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

class NewsAPIRateLimiter:
    def __init__(self):
        self.daily_limit = int(os.getenv("NEWS_API_DAILY_LIMIT", "100"))
        self.requests_per_second = int(os.getenv("NEWS_API_REQUESTS_PER_SECOND", "1"))
        self.request_count = 0
        self.last_reset = datetime.now()

    def can_make_request(self) -> bool:
        if datetime.now() - self.last_reset > timedelta(days=1):
            self.request_count = 0
            self.last_reset = datetime.now()
        return self.request_count < self.daily_limit

    def increment_count(self):
        self.request_count += 1

class NewsScraper:
    """Handles scraping articles from the News API."""

    def __init__(self, db_manager):
        load_dotenv()
        self.db_manager = db_manager
        self.article_manager = ArticleManager(db_manager)
        self.search_term_manager = SearchTermManager(db_manager)
        self.NEWS_API_KEY = os.getenv("NEWS_API_KEY")
        self.NEWS_API_URL = os.getenv("NEWS_API_URL")
        self.rate_limiter = NewsAPIRateLimiter()
    
        if not self.NEWS_API_KEY or not self.NEWS_API_URL:
            logging.error("NEWS_API_KEY and NEWS_API_URL must be set in your environment variables.")
            raise ValueError("NEWS_API_KEY and NEWS_API_URL must be set in your environment variables.")

    @sleep_and_retry
    @limits(calls=1, period=1)  # 1 call per second
    def make_api_request(self, params: Dict) -> requests.Response:
        if not self.rate_limiter.can_make_request():
            raise Exception("Daily API limit reached")
        
        response = requests.get(self.NEWS_API_URL, params=params)
        self.rate_limiter.increment_count()
        return response

    def fetch_articles_for_term(self, search_term):
        """Fetch articles for a given search term using the News API."""
        articles = []
        params = {
            "q": search_term,
            "apiKey": self.NEWS_API_KEY,
            "pageSize": 100,
            "page": 1
        }

        while True:
            try:
                response = self.make_api_request(params)
                if response.status_code != 200:
                    logging.error(f"Error fetching articles for '{search_term}': {response.status_code}")
                    break

                data = response.json()
                new_articles = data.get("articles", [])
                if not new_articles:
                    break

                articles.extend(new_articles)
                if len(new_articles) < params["pageSize"]:
                    break

                params["page"] += 1

            except Exception as e:
                logging.error(f"Request exception occurred while fetching articles for '{search_term}': {e}")
                break

        return articles

    def insert_articles_into_database(self, articles, database):
        """Insert articles into the specified database with error handling."""
        if not articles:
            logging.error("No articles to insert into %s", database)
            return

        for article in articles:
            try:
                # Extract article data with fallbacks
                article_data = {
                    'title': article.get('title', ''),
                    'description': article.get('description', ''),
                    'url': article.get('url', ''),
                    'source_name': article.get('source', {}).get('name', ''),
                    'author': article.get('author', ''),
                    'published_at': article.get('publishedAt', None),
                    'content': article.get('content', '')
                }

                # Skip articles missing required fields
                if not all([article_data['title'], article_data['url']]):
                    logging.warning(f"Skipping article due to missing required fields: {article_data}")
                    continue
                
                # Check if article already exists by URL
                if self.article_manager.article_exists(article_data['url']):
                    logging.info(f"Article already exists: {article_data['url']}")
                    continue

                # Insert the article
                self.article_manager.insert_article(article_data)
                logging.info(f"Successfully inserted article: {article_data['title']}")

            except Exception as e:
                logging.error(f"Error inserting article: {str(e)}")
                continue

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
            articles = self.fetch_articles_for_term(search_term)
            self.insert_articles_into_database(articles, "raw_articles")

if __name__ == "__main__":
    # Initialize NewsScraper
    db_manager = DatabaseManager()
    news_scraper = NewsScraper(db_manager)
    news_scraper.scrape_articles()