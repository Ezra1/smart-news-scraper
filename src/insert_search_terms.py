# In insert_search_terms.py
from src.database_manager import DatabaseManager, SearchTermManager
from src.logger_config import setup_logging

logger = setup_logging(__name__)

if __name__ == "__main__":
    db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
    db_path = db_path if db_path else "news_articles.db"

    db_manager = DatabaseManager(db_path)
    search_term_manager = SearchTermManager(db_manager)
    
    txt_file = input("Enter path to search terms file (leave blank for default 'search_terms.txt'): ").strip()
    txt_file = txt_file if txt_file else "search_terms.txt"

    search_term_manager.insert_search_terms_from_txt(txt_file)