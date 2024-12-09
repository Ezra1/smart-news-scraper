"""src/app.py"""

import logging
import os
import sys
import logging.config
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.database import DatabaseManager, ArticleManager, SearchTermManager
from src.news_scraper import NewsScraper
from src.relevance_filtering import BatchProcessor
from src.sort_cleaned_tables import RelevanceFilter

# Load environment variables and set up logging
current_directory = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')

# Set up logging
logging.config.fileConfig(logging_config_path)
logger = logging.getLogger(__name__)

def main():
    """Main application entry point."""
    # Load environment variables from .env
    load_dotenv()

    try:
        # Initialize managers
        db_manager = DatabaseManager()
        search_term_manager = SearchTermManager(db_manager)
        article_manager = ArticleManager(db_manager)
        news_scraper = NewsScraper(db_manager)
        relevance_filtering = BatchProcessor(db_manager)  # Pass db_manager
        sort_cleaned_tables = RelevanceFilter(article_manager)

        # Step 1: Refresh search terms from config/search_terms.json
        logging.info("Refreshing search terms...")
        search_term_manager.refresh_search_terms()
        logging.info("Search terms refreshed successfully.")

        # Step 2: Scrape articles based on the search terms
        logging.info("Starting news scraping...")
        news_scraper.scrape_articles()
        logging.info("News scraping completed successfully.")

        # Step 3: Create a batch, process articles, and upload the batch for analysis
        logging.info("Starting batch processing for relevance analysis...")
        relevance_filtering.process_batch()
        logging.info("Batch processing completed successfully.")

        # Step 4: Process batch results to insert relevant articles into the database
        logging.info("Processing batch results to determine relevant articles...")
        sort_cleaned_tables.process_latest_results()
        logging.info("Batch results processed successfully.")

        # Step 5: Print analysis results (optional)
        sort_cleaned_tables.analyze_results()

    except Exception as error:
        logging.error(f"An error occurred: {error}")
        raise  # Re-raise the exception for proper error handling

if __name__ == "__main__":
    main()