import logging
import os
from database import DatabaseManager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SearchTermManager:
    """Manages operations related to search terms, including insertion and batch loading."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def insert_search_term(self, term: str):
        """Insert a single search term into the database, avoiding duplicates."""
        try:
            with self.db_manager.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("INSERT OR IGNORE INTO search_terms (term) VALUES (?);", (term,))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Error inserting term '{term}': {e}")

    def insert_search_terms_from_txt(self, txt_file: str = "search_terms.txt"):
        """Insert search terms from a TXT file into the search_terms table."""
        if not os.path.exists(txt_file):
            logger.error(f"❌ Search terms file '{txt_file}' not found.")
            print(f"❌ Error: The file '{txt_file}' does not exist.")
            return

        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                terms = {line.strip().lower() for line in f if line.strip()}  # Remove duplicates & empty lines

                if not terms:
                    logger.warning("⚠️ No search terms found in the file.")
                    print("⚠️ Warning: No search terms found in the file.")
                    return

                for term in terms:
                    self.insert_search_term(term)

                logger.info(f"✅ Successfully inserted {len(terms)} unique search terms.")
                print(f"✅ Successfully inserted {len(terms)} unique search terms.")
        except Exception as e:
            logger.error(f"❌ Error reading search terms from '{txt_file}': {e}")
            print(f"❌ Error processing '{txt_file}': {e}")

if __name__ == "__main__":
    # Allow user to specify a database file
    db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
    db_path = db_path if db_path else "news_articles.db"

    db_manager = DatabaseManager(db_path)
    search_term_manager = SearchTermManager(db_manager)

    # Allow user to specify a search terms file
    txt_file = input("Enter path to search terms file (leave blank for default 'search_terms.txt'): ").strip()
    txt_file = txt_file if txt_file else "search_terms.txt"

    search_term_manager.insert_search_terms_from_txt(txt_file)
