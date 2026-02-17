# In insert_search_terms.py
from pathlib import Path

from src.database_manager import DatabaseManager, SearchTermManager
from src.logger_config import setup_logging
from src.utils.path_validator import validate_path

logger = setup_logging(__name__)

if __name__ == "__main__":
    db_path_input = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
    db_path_input = db_path_input if db_path_input else "news_articles.db"
    try:
        db_path = str(validate_path(db_path_input, base_dir=Path.cwd(), must_exist=False))
    except ValueError as e:
        print(f"Invalid database path: {e}")
        raise SystemExit(1)

    db_manager = DatabaseManager(db_path)
    search_term_manager = SearchTermManager(db_manager)
    
    txt_file_input = input("Enter path to search terms file (leave blank for default 'search_terms.txt'): ").strip()
    txt_file_input = txt_file_input if txt_file_input else "search_terms.txt"
    try:
        txt_file = str(validate_path(txt_file_input, base_dir=Path.cwd(), must_exist=True))
    except ValueError as e:
        print(f"Invalid search terms path: {e}")
        raise SystemExit(1)

    search_term_manager.insert_search_terms_from_txt(txt_file)