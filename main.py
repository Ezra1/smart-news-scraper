import os
import logging
import sys
from pathlib import Path

# Add the project root to the Python path
current_dir = Path(__file__).resolve().parent
src_dir = current_dir / "src"
sys.path.append(str(src_dir))

# Now import the modules
from database import DatabaseManager, ArticleManager, SearchTermManager
from news_scraper import NewsArticleScraper
from relevance_filtering import ArticleProcessor
from validation import ArticleValidator
from duplication import ArticleDeduplicator
from sort_cleaned_tables import RelevanceFilter
from config import ConfigManager
from extract_cleaned_data import extract_cleaned_data

# Update logging configuration
LOG_FILE = "news_scraper.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def setup_directories():
    """Create necessary directories if they don't exist"""
    directories = [
        "batch/input",
        "batch/output",
        "output"
    ]
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)

def database_transaction(db: DatabaseManager):
    """Context manager for database transactions"""
    class TransactionContextManager:
        def __init__(self, db):
            self.db = db
            self.connection = None

        def __enter__(self):
            self.connection = self.db.get_connection().__enter__()
            return self.connection

        def __exit__(self, exc_type, exc_val, exc_tb):
            if (exc_type is None):
                self.connection.commit()
            else:
                self.connection.rollback()
            return self.db.get_connection().__exit__(exc_type, exc_val, exc_tb)

    return TransactionContextManager(db)

async def main():
    setup_directories()
    print("\nSmart News Scraper - Interactive Mode\n")
    db = None

    try:
        config_manager = ConfigManager()
        if not config_manager.validate():
            logger.error("Configuration error: Missing API keys")
            print("Configuration error: Missing API keys")
            print("Please update your config.json file.")
            return

        db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
        db_path = db_path if db_path else "news_articles.db"
        db = DatabaseManager(db_path)
        
        search_manager = SearchTermManager(db)
        article_manager = ArticleManager(db)
        processor = ArticleProcessor()  # Changed from BatchProcessor to ArticleProcessor
        scraper = NewsArticleScraper(config_manager)

        search_terms_file = input("Enter path to search_terms.txt (leave blank for default): ").strip()
        search_terms_file = search_terms_file if search_terms_file else "search_terms.txt"

        delete_old = input("Delete old articles before starting? (Y/N): ").strip().lower() == "y"
        if delete_old:
            db.execute_query("DELETE FROM raw_articles;")
            db.execute_query("DELETE FROM cleaned_articles;")

        print(f"Loading search terms from {search_terms_file}...")
        search_manager.insert_search_terms_from_txt(search_terms_file)

        try:
            search_terms = search_manager.get_search_terms()
            if not search_terms:
                logger.error("No search terms found. Exiting.")
                print("No search terms found. Exiting.")
                return

            print("Fetching articles...")
            articles = await scraper.fetch_all_articles(search_terms)
            if scraper.rate_limited:
                print("Rate limit reached. Proceeding with available articles...")
            
            if articles:
                for article in articles:
                    article_manager.insert_article(article, article['search_term_id'])
                
                print(f"Processing {len(articles)} articles...")
                articles_to_process = article_manager.get_articles()
                # Change: Add await since process_articles is now async
                results = await processor.process_articles(articles_to_process)
                if results:
                    print("Processing batch for relevance filtering...")
                    relevance_filter = RelevanceFilter(article_manager)
                    relevance_filter.process_latest_results()
                    relevance_filter.analyze_results()
            else:
                print("No articles fetched. Proceeding with existing data...")
                articles_to_process = article_manager.get_articles()
                if articles_to_process:
                    print("Processing existing articles...")
                    # Change: Add await since process_articles is now async
                    results = await processor.process_articles(articles_to_process)
                    if results:
                        relevance_filter = RelevanceFilter(article_manager)
                        relevance_filter.process_latest_results()
                        relevance_filter.analyze_results()

            print("\nProcessing completed.")

            # Extract cleaned and relevant data
            output_file = "/home/turambar/projects/smart-news-scraper/output/cleaned_articles.txt"
            extract_cleaned_data(db_path, output_file)
            print(f"Cleaned and relevant data extracted to {output_file}")

        except Exception as e:
            logger.error(f"Error during processing: {e}")
            print(f"Error during processing: {e}")
            
    except Exception as e:
        logger.error(f"Process failed: {e}")
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        if db is not None:
            db.close()
            logger.info("Database connection closed")
        else:
            logger.info("No database connection to close")

if __name__ == "__main__":
    import asyncio
    import signal
    import sys
    
    def signal_handler(sig, frame):
        """Handle graceful shutdown on SIGINT"""
        print("\nShutting down gracefully...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)