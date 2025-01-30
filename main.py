import os
import logging
import sys
from typing import Optional, List, Dict
from contextlib import contextmanager

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "src/"))
sys.path.append(project_root)

from database import DatabaseManager, ArticleManager, SearchTermManager
from relevance_filtering import BatchProcessor
from validation import ArticleValidator
from duplication import ArticleDeduplicator
from sort_cleaned_tables import RelevanceFilter
from config import ConfigManager

# Set up logging
LOG_FILE = "news_scraper.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class NewsArticleScraper:
    """Handles article scraping and processing"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.api_key = self.config.get("NEWS_API_KEY")
        self.api_url = self.config.get("NEWS_API_URL")
        
    async def fetch_articles(self, search_term: str) -> List[Dict]:
        """Fetch articles for a given search term"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'q': search_term,
                    'apiKey': self.api_key,
                    'language': 'en',
                    'sortBy': 'publishedAt'
                }
                
                async with session.get(self.api_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('articles', [])
                    else:
                        logger.error(f"API request failed: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Error fetching articles: {e}")
            return []

def process_articles(db: DatabaseManager, processor: BatchProcessor, 
                    validator: ArticleValidator, deduplicator: ArticleDeduplicator) -> None:
    """Process articles with validation and deduplication"""
    raw_articles = db.execute_query("SELECT * FROM raw_articles;") or []
    
    validated_articles = [
        article for article in raw_articles 
        if validator.clean_article(article)
    ]
    
    unique_articles = deduplicator.remove_duplicates(validated_articles)
    
    # Clear and reinsert articles
    db.execute_query("DELETE FROM raw_articles;")
    for article in unique_articles:
        db.execute_query("""
            INSERT INTO raw_articles (
                title, content, source, url, url_to_image, published_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            article["title"], article["content"], article["source_name"],
            article["url"], article["url_to_image"], article["published_at"]
        ))
    
    logger.info(f"Processed {len(unique_articles)} unique articles")

@contextmanager
def database_transaction(db: DatabaseManager):
    """Context manager for database transactions"""
    with db.get_connection() as connection:
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

async def main():
    """Main execution flow with proper transaction management"""
    print("\nSmart News Scraper - Interactive Mode\n")

    try:
        # Initialize configuration
        config_manager = ConfigManager()
        if not config_manager.validate():
            logger.error("Configuration error: Missing API keys")
            print("Configuration error: Missing API keys")
            print("Please update your config.json file.")
            return

        # Get database path
        db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
        db_path = db_path if db_path else "news_articles.db"

        # Initialize components
        db = DatabaseManager(db_path)
        search_manager = SearchTermManager(db)
        processor = BatchProcessor()
        article_validator = ArticleValidator()
        article_deduplicator = ArticleDeduplicator()
        relevance_filter = RelevanceFilter(db)
        scraper = NewsArticleScraper(config_manager)

        # Get search terms file path
        search_terms_file = input(
            "Enter the path to search_terms.txt (leave blank for default 'search_terms.txt'): "
        ).strip()
        search_terms_file = search_terms_file if search_terms_file else "search_terms.txt"

        if not os.path.exists(search_terms_file):
            logger.error(f"Search terms file '{search_terms_file}' not found")
            print(f"File '{search_terms_file}' not found. Exiting...")
            return

        # Execute main process with transaction management
        with database_transaction(db) as transaction:
            # Handle article deletion if requested
            delete_old_articles = input("Delete old articles before starting? (Y/N): ").strip().lower() == "y"
            if delete_old_articles:
                print("Deleting old articles...")
                db.execute_query("DELETE FROM raw_articles;")
                db.execute_query("DELETE FROM cleaned_articles;")
                print("Old articles deleted.")

            # Insert search terms
            print(f"Loading search terms from {search_terms_file}...")
            search_manager.insert_search_terms_from_txt(search_terms_file)

            # Fetch and process articles
            search_terms = search_manager.get_search_terms()
            print("Fetching articles...")
            for term in search_terms:
                articles = await scraper.fetch_articles(term['term'])
                for article in articles:
                    article_manager = ArticleManager(db)
                    article_manager.insert_article(article, term['id'])

            # Process articles
            print("Processing articles...")
            process_articles(db, processor, article_validator, article_deduplicator)

            # Process relevance filtering
            print("Processing batch for relevance filtering...")
            processor.process_articles()

            # Sort and analyze results
            print("Sorting cleaned articles...")
            relevance_filter.process_latest_results()
            relevance_filter.analyze_results()

            print("\nAll processes completed successfully.")

    except Exception as e:
        logger.error(f"Process failed: {e}")
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())