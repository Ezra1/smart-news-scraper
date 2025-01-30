"""src/database.py: Handles all database operations using SQLite"""

import os
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict

class DatabaseManager:
    """Manages SQLite database operations"""

    def __init__(self, db_path: str = "news_articles.db"):
        """Initialize database connection and create tables if they don't exist"""
        self.db_path = db_path
        self._create_tables()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Access columns by name
            yield conn
        except sqlite3.Error as e:
            logging.error(f"❌ Database connection error: {e}")
            raise
        finally:
            conn.close()

    def _create_tables(self):
        """Create necessary database tables if they don't exist"""
        with self.get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS search_terms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        term TEXT NOT NULL UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                cur.execute('''
                    CREATE TABLE IF NOT EXISTS raw_articles (
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
                    )
                ''')

                cur.execute('''
                    CREATE TABLE IF NOT EXISTS cleaned_articles (
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
                    )
                ''')

                conn.commit()
            except sqlite3.Error as e:
                logging.error(f"❌ Error creating database tables: {e}")
                conn.rollback()
                raise

    def execute_query(self, query: str, params: tuple = None) -> Optional[List[Dict]]:
        """Execute a SQL query and return results (if applicable)"""
        with self.get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(query, params or ())
                if query.strip().upper().startswith("SELECT"):
                    return [dict(row) for row in cur.fetchall()]
                conn.commit()
                return None
            except sqlite3.Error as e:
                logging.error(f"❌ Database query error: {e} | Query: {query}")
                conn.rollback()
                return None

class ArticleManager:
    """Handles article-related database operations"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def article_exists(self, url: str) -> bool:
        """Check if an article already exists in the database"""
        query = "SELECT 1 FROM raw_articles WHERE url = ?"
        result = self.db_manager.execute_query(query, (url,))
        return bool(result)

    def insert_article(self, article_data: dict, search_term_id: int) -> Optional[int]:
        """Insert an article into the raw_articles table"""
        if self.article_exists(article_data['url']):
            logging.info(f"⚠️ Skipping duplicate article: {article_data['url']}")
            return None
        
        query = """
            INSERT INTO raw_articles (
                search_term_id, title, content, source, url, 
                url_to_image, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            search_term_id,
            article_data['title'],
            article_data['content'],
            article_data['source_name'],
            article_data['url'],
            article_data.get('url_to_image'),
            article_data['published_at']
        )

        try:
            with self.db_manager.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, params)
                conn.commit()
                return cur.lastrowid
        except sqlite3.Error as e:
            logging.error(f"❌ Error inserting article '{article_data['title']}': {e}")
            return None

    def get_articles(self, article_id: Optional[int] = None) -> Optional[Dict]:
        """Retrieve a single article by ID or all articles"""
        query = "SELECT * FROM raw_articles WHERE id = ?" if article_id else "SELECT * FROM raw_articles ORDER BY published_at DESC"
        result = self.db_manager.execute_query(query, (article_id,) if article_id else None)
        return result[0] if article_id and result else result

class SearchTermManager:
    """Handles search term-related database operations"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def get_search_terms(self) -> List[Dict]:
        """Retrieve all search terms"""
        return self.db_manager.execute_query("SELECT id, term FROM search_terms") or []

    def refresh_search_terms(self, search_terms: List[str]):
        """Refresh the search terms table with new terms"""
        with self.db_manager.get_connection() as conn:
            cur = conn.cursor()
            try:
                # Clear existing terms
                cur.execute("DELETE FROM search_terms")

                # Insert new terms
                for term in search_terms:
                    cur.execute("INSERT INTO search_terms (term) VALUES (?)", (term,))

                conn.commit()
                logging.info(f"✅ Successfully refreshed {len(search_terms)} search terms.")
            except sqlite3.Error as e:
                logging.error(f"❌ Error refreshing search terms: {e}")
                conn.rollback()
                raise

if __name__ == "__main__":
    # Allow user to specify a database file
    db_path = input("Enter database file path (leave blank for default 'news_articles.db'): ").strip()
    db_path = db_path if db_path else "news_articles.db"

    # Initialize database manager and ensure tables exist
    db_manager = DatabaseManager(db_path)
    search_term_manager = SearchTermManager(db_manager)

    print("✅ Database setup complete. Available search terms:")
    for term in search_term_manager.get_search_terms():
        print(f"- {term['term']}")
