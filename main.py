import os
import sys
from pathlib import Path

from src.logger_config import setup_logging
logger = setup_logging(__name__)

# Update imports to match correct file names
from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
from src.news_scraper import NewsArticleScraper
from src.openai_relevance_processing import ArticleProcessor
from src.extract_cleaned_articles import extract_cleaned_data
from src.config import ConfigManager
from src.insert_processed_articles import RelevanceFilter
from src.analysis_utils import analyze_relevance_results, print_analysis_results

# Remove the old logging configuration and continue with existing code
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
        processor = ArticleProcessor()
        scraper = NewsArticleScraper(config_manager)

        search_terms_file = input("Enter path to search_terms.txt (leave blank for default): ").strip()
        search_terms_file = search_terms_file if search_terms_file else "search_terms.txt"

        delete_old_raw = input("Delete old raw articles before starting? (Y/N): ").strip().lower() == "y"
        if delete_old_raw:
            db.execute_query("DELETE FROM raw_articles;")

        delete_old_relevant = input("Delete old relevant articles before starting? (Y/N): ").strip().lower() == "y"
        if delete_old_relevant:
            db.execute_query("DELETE FROM relevant_articles;")

        print(f"Loading search terms from {search_terms_file}...")
        search_manager.insert_search_terms_from_txt(search_terms_file)

        try:
            # Retrieve search terms from the database
            search_terms = search_manager.get_search_terms()
            if not search_terms:
                # Log and print an error if no search terms are found, then exit
                logger.error("No search terms found. Exiting.")
                print("No search terms found. Exiting.")
                return

            print("Fetching articles...")
            # Fetch all articles based on the search terms
            articles = await scraper.fetch_all_articles(search_terms)
            if scraper.rate_limited:
                # Print a message if rate limit is reached
                print("Rate limit reached. Proceeding with available articles...")

            if articles:
                # Insert each fetched article into the database
                for article in articles:
                    # Article data is already properly structured from news_scraper
                    article_manager.insert_article(article)
                
                # Print the number of articles being processed
                print(f"Processing {len(articles)} articles...")
                # Retrieve articles to process for relevance filtering
                articles_to_process = article_manager.get_articles()
                # Process the articles using the ArticleProcessor
                results = await processor.process_articles(articles_to_process)
                if results:
                    # Print a message indicating the start of relevance filtering
                    print("Processing for relevance filtering...")
                    # Initialize the RelevanceFilter with the article manager
                    relevance_filter = RelevanceFilter(article_manager)
                    # Process the latest results for relevance
                    relevance_filter.process_latest_results()
                    # Analyze the processed results
                    relevance_filter.analyze_results()
            else:
                # Print a message if no articles were fetched
                print("No articles fetched. Proceeding with existing data...")
                # Retrieve existing articles from the database
                articles_to_process = article_manager.get_articles()
                if articles_to_process:
                    # Print a message indicating the processing of existing articles
                    print("Processing existing articles...")
                    # Process the existing articles using the ArticleProcessor
                    results = await processor.process_articles(articles_to_process)
                    if results:
                        # Initialize the RelevanceFilter with the article manager
                        relevance_filter = RelevanceFilter(article_manager)
                        # Analyze the processed results
                        relevance_filter.analyze_results()

            # Print a message indicating the completion of processing
            print("\nProcessing completed.")

            # Define the output file path for relevant articles
            desktop_path = str(Path.home() / "Desktop")
            output_file = str(Path(desktop_path) / "relevant_articles.txt")
            
            # Extract relevant articles from the database and save them to the output file
            extract_cleaned_data(db_path, output_file)
            print(f"Relevant articles extracted to {output_file}")

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