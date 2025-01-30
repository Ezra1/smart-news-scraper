"""src/database.py: Handles all database operations using SQLite with enhanced transaction safety"""

import os
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages SQLite database operations with enhanced connection management"""

    def __init__(self, db_path: str = "news_articles.db"):
        """Initialize database connection and create tables if they don't exist"""
        self.db_path = db_path
        self._connection = None
        self._create_tables()

    @property
    def connection(self):
        """Lazy connection initialization"""
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.db_path,
                timeout=60.0,
                isolation_level='IMMEDIATE'
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self):
        """Explicitly close the database connection"""
        if self._connection is not None:
            try:
                self._connection.close()
                self._connection = None
            except sqlite3.Error as e:
                logging.error(f"Error closing database connection: {e}")

    @contextmanager
    def get_connection(self):
        """Get a database connection with proper timeout and isolation level"""
        try:
            yield self.connection
        except sqlite3.Error as e:
            logging.error(f"Database connection error: {e}")
            raise

    def execute_query(self, query: str, params: tuple = None) -> Optional[List[Dict]]:
        """Execute a SQL query with proper transaction handling"""
        try:
            cur = self.connection.cursor()
            cur.execute(query, params or ())
            if query.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cur.fetchall()]
            self.connection.commit()
            return None
        except sqlite3.Error as e:
            self.connection.rollback()
            logging.error(f"Database query error: {e} | Query: {query}")
            raise

    def __del__(self):
        """Ensure connection is closed when object is destroyed"""
        self.close()

    def _create_tables(self):
        """Create necessary database tables with proper error handling"""
        queries = [
            '''CREATE TABLE IF NOT EXISTS search_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS raw_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_term_id INTEGER,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                url_to_image TEXT,
                published_at TIMESTAMP NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (search_term_id) REFERENCES search_terms (id)
            )''',
            '''CREATE TABLE IF NOT EXISTS cleaned_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_article_id INTEGER,
                relevance_score REAL CHECK (relevance_score >= 0 AND relevance_score <= 1),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                url_to_image TEXT,
                published_at TIMESTAMP NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (raw_article_id) REFERENCES raw_articles (id)
            )'''
        ]

        with self.get_connection() as conn:
            cur = conn.cursor()
            try:
                for query in queries:
                    cur.execute(query)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                logging.error(f"Error creating database tables: {e}")
                raise

class ArticleManager:
    """Handles article-related database operations with enhanced safety"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def article_exists(self, url: str) -> bool:
        """Check if an article already exists with proper error handling"""
        try:
            query = "SELECT 1 FROM raw_articles WHERE url = ?"
            result = self.db_manager.execute_query(query, (url,))
            return bool(result)
        except sqlite3.Error:
            return False

    def insert_article(self, article_data: dict, search_term_id: int) -> Optional[int]:
        """Insert an article with proper transaction handling"""
        if self.article_exists(article_data['url']):
            logging.info(f"Skipping duplicate article: {article_data['url']}")
            return None

        query = """
            INSERT INTO raw_articles (
                search_term_id, title, content, source, url, 
                url_to_image, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        # Handle the source field correctly - it might be nested in a 'source' object
        source = article_data.get('source', {})
        source_name = source.get('name') if isinstance(source, dict) else str(source)

        params = (
            search_term_id,
            article_data['title'],
            article_data['content'],
            source_name,
            article_data['url'],
            article_data.get('urlToImage'),  # Note: API uses camelCase
            article_data['publishedAt']  # Note: API uses camelCase
        )

        try:
            with self.db_manager.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, params)
                conn.commit()
                return cur.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error inserting article '{article_data['title']}': {e}")
            return None

    def get_articles(self, article_id: Optional[int] = None) -> Optional[Dict]:
        """Retrieve articles with proper error handling"""
        try:
            query = "SELECT * FROM raw_articles WHERE id = ?" if article_id else \
                   "SELECT * FROM raw_articles ORDER BY published_at DESC"
            result = self.db_manager.execute_query(query, (article_id,) if article_id else None)
            return result[0] if article_id and result else result
        except sqlite3.Error as e:
            logging.error(f"Error retrieving articles: {e}")
            return None

class SearchTermManager:
    """Manages operations related to search terms, including insertion, retrieval, and batch loading."""

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

    def get_search_terms(self) -> List[Dict]:
        """Retrieve all search terms from the database."""
        return self.db_manager.execute_query("SELECT id, term FROM search_terms") or []

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

    def refresh_search_terms(self, search_terms: List[str]):
        """Refresh the search terms table with new terms."""
        with self.db_manager.get_connection() as conn:
            cur = conn.cursor()
            try:
                # Clear existing terms
                cur.execute("DELETE FROM search_terms")

                # Insert new terms
                for term in search_terms:
                    cur.execute("INSERT INTO search_terms (term) VALUES (?)", (term,))

                conn.commit()
                logger.info(f"✅ Successfully refreshed {len(search_terms)} search terms.")
            except sqlite3.Error as e:
                logger.error(f"❌ Error refreshing search terms: {e}")
                conn.rollback()
                raise

if __name__ == "__main__":
    try:
        db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
        db_path = db_path if db_path else "news_articles.db"

        db_manager = DatabaseManager(db_path)
        search_term_manager = SearchTermManager(db_manager)

        print("Database setup complete. Available search terms:")
        for term in search_term_manager.get_search_terms():
            print(f"- {term['term']}")
    except Exception as e:
        logging.error(f"Database initialization error: {e}")
        print(f"Error: {e}")
        exit(1)