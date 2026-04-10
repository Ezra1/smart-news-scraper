"""Interactive CLI entrypoint for the Smart News Scraper.

This script guides users through configuring credentials, selecting database
locations, loading search terms, and running the end-to-end scraping, cleaning,
and relevance-analysis pipeline. Run it from the repository root:

    python main.py

Key prompts:
- Database path (defaults to data/news_articles.db)
- Path to search_terms.txt (defaults to data/search_terms.txt)
- Whether to clear existing raw or relevant articles before processing

Example usage:
    $ python main.py
    Enter database file path (leave blank for default 'data/news_articles.db'):
    Enter path to search_terms.txt (leave blank for default):
    Delete old raw articles before starting? (Y/N):
    Delete old relevant articles before starting? (Y/N):
"""

import os
import sys
import traceback
from pathlib import Path

# Add error handling at the very top
try:
    print("Starting program...")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print(f"Command line arguments: {sys.argv}")
    
    from src.logger_config import setup_logging
    logger = setup_logging(__name__)
    logger.info("Logger initialized")
    
    print("Importing required modules...")
    # Update imports to match correct file names
    from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
    logger.info("Database modules imported")
    
    from src.news_scraper import NewsArticleScraper
    logger.info("News scraper module imported")
    
    from src.openai_relevance_processing import ArticleProcessor
    logger.info("OpenAI processing module imported")
    
    from src.extract_cleaned_articles import extract_cleaned_data
    logger.info("Article extraction module imported")
    
    from src.config import ConfigManager
    logger.info("Config module imported")
    
    from src.insert_processed_articles import RelevanceFilter
    logger.info("Relevance filter module imported")
    
    from src.analysis_utils import analyze_relevance_results, print_analysis_results
    from src.utils.path_validator import validate_path
    from src.pipeline_factory import create_pipeline
    logger.info("Analysis utils module imported")
    
    print("All modules imported successfully")

    def setup_directories():
        """Create default data, log, and batch directories if missing.

        Ensures that batch/input, batch/output, output, logs, and data
        directories exist before any file operations occur.
        """
        directories = [
            "batch/input",
            "batch/output",
            "output",
            "logs",
            "data"
        ]
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)

    def database_transaction(db: DatabaseManager):
        """Context manager that wraps database work in a commit/rollback guard.

        Args:
            db: DatabaseManager instance that owns the connection.

        Returns:
            A context manager that commits on success and rolls back on errors.
        """
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
        """Run the interactive scraping and processing workflow.

        Prompts for configuration (database path, search terms file, cleanup
        choices), fetches articles via NewsAPI, processes relevance with OpenAI,
        persists results, and exports relevant articles to the Desktop.

        Returns:
            None. Side effects include database mutations and file export.
        """
        print("Starting Smart News Scraper...")
        setup_directories()
        print("\nSmart News Scraper - Interactive Mode\n")
        db = None
        results_exported_this_session = False

        try:
            config_manager = ConfigManager()
            if not config_manager.validate():
                logger.error("Configuration error: Missing API keys")
                print("Configuration error: Missing API keys")
                print("Please update your config/config.json file.")
                return

            db_path_input = input("Enter database file path (leave blank for default 'data/news_articles.db'): ").strip()
            db_path_input = db_path_input if db_path_input else "data/news_articles.db"
            try:
                db_path = str(validate_path(db_path_input, base_dir=Path("data").resolve(), must_exist=False))
            except ValueError as e:
                print(f"Invalid database path: {e}")
                return
            pipeline = create_pipeline(db_path=db_path, config_manager=config_manager)
            db = pipeline["db_manager"]
            search_manager = SearchTermManager(db)
            article_manager = ArticleManager(db)
            processor = pipeline["processor"]
            scraper = pipeline["scraper"]

            search_terms_file_input = input("Enter path to search_terms.txt (leave blank for default): ").strip()
            search_terms_file_input = search_terms_file_input if search_terms_file_input else "data/search_terms.txt"
            try:
                search_terms_file = str(validate_path(search_terms_file_input, base_dir=Path("data").resolve(), must_exist=True))
            except ValueError as e:
                print(f"Invalid search terms path: {e}")
                return

            db.execute_query("DELETE FROM raw_articles;")

            existing_relevant_rows = db.get_table_row_count("relevant_articles")
            if existing_relevant_rows > 0:
                if not results_exported_this_session:
                    print(
                        "\nRelevant articles already exist and were not exported this session.\n"
                        "Choose one option before continuing:"
                    )
                    print("1) Clear results")
                    print("2) Export and clear results")
                    choice = input("Enter 1 or 2: ").strip()
                    if choice == "2":
                        default_output = str(Path.home() / "Desktop" / "relevant_articles.txt")
                        export_path_input = input(
                            f"Enter export file path (leave blank for '{default_output}'): "
                        ).strip()
                        export_path = export_path_input or default_output
                        try:
                            extract_cleaned_data(db_path, export_path)
                            print(f"Relevant articles exported to {export_path}")
                            results_exported_this_session = True
                        except Exception as e:
                            logger.error(f"Export before clear failed: {e}")
                            print(f"Export failed: {e}")
                            print("Aborting run to avoid deleting unexported results.")
                            return
                    elif choice != "1":
                        print("Run cancelled. No results were cleared.")
                        return
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
                    relevant_articles = [r.article for r in results if getattr(r, "status", "") == "relevant" and getattr(r, "article", None)]
                    error_count = len([r for r in results if getattr(r, "status", "") == "error"])
                    if error_count:
                        print(f"Encountered {error_count} processing errors.")
                    if relevant_articles:
                        # Print a message indicating the start of relevance filtering
                        print("Processing for relevance filtering...")
                        # Initialize the RelevanceFilter with the article manager
                        relevance_filter = RelevanceFilter(article_manager)
                        # Process the latest results for relevance
                        relevance_filter.process_latest_results()
                        # Analyze the processed results
                        relevance_filter.analyze_results()
                        results_exported_this_session = False
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
                        relevant_articles = [r.article for r in results if getattr(r, "status", "") == "relevant" and getattr(r, "article", None)]
                        error_count = len([r for r in results if getattr(r, "status", "") == "error"])
                        if error_count:
                            print(f"Encountered {error_count} processing errors.")
                        if relevant_articles:
                            # Initialize the RelevanceFilter with the article manager
                            relevance_filter = RelevanceFilter(article_manager)
                            # Analyze the processed results
                            relevance_filter.analyze_results()
                            results_exported_this_session = False

                # Print a message indicating the completion of processing
                print("\nProcessing completed.")

                # Define the output file path for relevant articles
                desktop_path = str(Path.home() / "Desktop")
                output_file = str(Path(desktop_path) / "relevant_articles.txt")
                
                # Extract relevant articles from the database and save them to the output file
                extract_cleaned_data(db_path, output_file)
                print(f"Relevant articles extracted to {output_file}")
                results_exported_this_session = True

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
            """Handle SIGINT to shut down gracefully.

            Args:
                sig: Signal number received.
                frame: Current stack frame when the signal was caught.
            """
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

except Exception as e:
    # Log the error to a file
    with open("error_log.txt", "w") as f:
        f.write(f"Error: {str(e)}\n")
        f.write(traceback.format_exc())
    print(f"Error: {str(e)}")
    print("Check error_log.txt for details")
    sys.exit(1)