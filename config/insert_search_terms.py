import json
import logging
import logging.config
from src.database import DatabaseManager

logging.config.fileConfig('logging.conf')
logger = logging.getLogger(__name__)
class SearchTermManager:
    """Manages operations related to search terms, including insertion and batch loading."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def insert_search_term(self, term):
        """Insert a single search term into the database."""
        conn = self.db_manager.get_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO search_terms (term)
                        VALUES (%s);
                    """, (term,))
                    conn.commit()
            except Exception as e:
                logging.error(f"Error inserting term '{term}': {e}")
            finally:
                conn.close()

    def insert_search_terms_from_json(self, json_file):
        """Insert search terms from a JSON file into the search_terms table."""
        try:
            # Open and load the JSON file
            with open(json_file, 'r') as f:
                data = json.load(f)
                terms = data.get('terms', [])

                # Insert each term into the database
                for term in terms:
                    self.insert_search_term(term)
                logging.info("Successfully inserted %s search terms.", {len(terms)})
                print(f"Successfully inserted {len(terms)} search terms.")
        except Exception as e:
            logging.error(f"Error processing the JSON file: {e}")

if __name__ == "__main__":
    # Initialize the database manager and search term manager
    db_manager = DatabaseManager()
    search_term_manager = SearchTermManager(db_manager)

    # Specify the JSON file containing the search terms
    json_file = 'search_terms.json'

    # Insert the search terms into the database
    search_term_manager.insert_search_terms_from_json(json_file)
