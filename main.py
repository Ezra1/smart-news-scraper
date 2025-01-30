import os
import logging
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "src/"))
sys.path.append(project_root)

from database import DatabaseManager
from relevance_filtering import BatchProcessor
from insert_search_terms import SearchTermManager
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

def main():
    print("\n📢 Smart News Scraper - Interactive Mode\n")

    # Load configuration
    config_manager = ConfigManager()
    if not config_manager.validate():
        print(f"\n❌ Configuration error: Missing API keys.")
        print("Please update your config.json file.")
        return

    # Get database path from user
    db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
    db_path = db_path if db_path else "news_articles.db"

    # Ensure database is set up
    db = DatabaseManager(db_path)
    search_manager = SearchTermManager(db)
    processor = BatchProcessor()
    article_validator = ArticleValidator()
    article_deduplicator = ArticleDeduplicator()
    relevance_filter = RelevanceFilter(db)

    # Prompt user for deleting old articles
    delete_old_articles = input("Delete old articles before starting? (Y/N): ").strip().lower() == "y"
    if delete_old_articles:
        try:
            print("🗑 Deleting old articles...")
            db.execute_query("DELETE FROM raw_articles;")
            db.execute_query("DELETE FROM cleaned_articles;")
            print("✅ Old articles deleted.")
        except Exception as e:
            logger.error(f"❌ Error deleting old articles: {e}")
            print(f"❌ Error: {e}")

    # Get search terms file path
    search_terms_file = input("Enter the path to search_terms.txt (leave blank for default 'search_terms.txt'): ").strip()
    search_terms_file = search_terms_file if search_terms_file else "search_terms.txt"

    # Validate search terms file
    if not os.path.exists(search_terms_file):
        print(f"❌ File '{search_terms_file}' not found. Exiting...")
        logger.error(f"Search terms file '{search_terms_file}' not found.")
        return

    # Insert search terms
    try:
        print(f"📄 Loading search terms from {search_terms_file}...")
        search_manager.insert_search_terms_from_txt(search_terms_file)
    except Exception as e:
        logger.error(f"❌ Error inserting search terms: {e}")
        print(f"❌ Error inserting search terms: {e}")
        return

    # Scrape articles
    try:
        print("🔎 Scraping articles...")
        scraper.scrape_articles()
    except Exception as e:
        logger.error(f"❌ Error scraping articles: {e}")
        print(f"❌ Error scraping articles: {e}")
        return

    # Validate and deduplicate articles
    try:
        print("🧼 Validating and deduplicating articles...")
        raw_articles = db.execute_query("SELECT * FROM raw_articles;") or []
        
        validated_articles = [article_validator.clean_article(article) for article in raw_articles if article_validator.clean_article(article)]
        unique_articles = article_deduplicator.remove_duplicates(validated_articles)

        # Clear raw articles table before reinserting
        db.execute_query("DELETE FROM raw_articles;")
        for article in unique_articles:
            db.execute_query("""
                INSERT INTO raw_articles (title, content, source, url, url_to_image, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (article["title"], article["content"], article["source_name"], article["url"], article["url_to_image"], article["published_at"]))

        print(f"✅ Validated and inserted {len(unique_articles)} unique articles.")

    except Exception as e:
        logger.error(f"❌ Error validating and deduplicating articles: {e}")
        print(f"❌ Error validating and deduplicating articles: {e}")
        return

    # Process relevance filtering
    try:
        print("📊 Processing batch for relevance filtering...")
        processor.process_articles()
    except Exception as e:
        logger.error(f"❌ Error processing articles: {e}")
        print(f"❌ Error processing articles: {e}")
        return

    # Sort cleaned tables and analyze results
    try:
        print("🗂 Sorting cleaned articles...")
        relevance_filter.process_latest_results()
        relevance_filter.analyze_results()
    except Exception as e:
        logger.error(f"❌ Error sorting cleaned articles: {e}")
        print(f"❌ Error sorting cleaned articles: {e}")
        return

    print("\n🎉 Done! All processes completed successfully.")

if __name__ == "__main__":
    main()
