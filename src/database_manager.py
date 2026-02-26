"""src/database.py: Handles all database operations using SQLite with enhanced transaction safety"""

import os
import sys
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any
import threading
from queue import Queue

from src.logger_config import setup_logging
logger = setup_logging(__name__)

class DatabaseManager:
    """Manages SQLite database operations with enhanced connection management"""
    _instance = None
    _lock = threading.Lock()
    _connection_pool = Queue(maxsize=10)  # Connection pool

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str = "news_articles.db"):
        if self._initialized:
            return

        self.db_path = self._resolve_db_path(db_path)
        self._initialized = True
        self._populate_pool()
        self._create_tables()  # Add this line

    def _resolve_db_path(self, db_path: str) -> str:
        """Resolve the database path and ensure its parent directory exists.

        For frozen (PyInstaller) builds, paths should be anchored to the bundle
        directory instead of the user's current working directory to avoid
        missing folders when the executable runs from arbitrary locations.
        """

        path = Path(db_path)

        if not path.is_absolute():
            base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            path = (base_path / path).resolve()

        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _populate_pool(self):
        """Initialize connection pool"""
        for _ in range(self._connection_pool.maxsize):
            conn = sqlite3.connect(
                self.db_path,
                timeout=60.0,
                isolation_level='IMMEDIATE',
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            self._connection_pool.put(conn)

    @contextmanager
    def get_connection(self):
        """Get connection from pool with proper timeout and isolation level"""
        connection = self._connection_pool.get()
        try:
            yield connection
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            # If there's an error, don't reuse the connection
            try:
                connection.close()
            except Exception:
                pass
            # Create a new connection to replace the closed one
            new_conn = sqlite3.connect(
                self.db_path,
                timeout=60.0,
                isolation_level='IMMEDIATE',
                check_same_thread=False
            )
            new_conn.row_factory = sqlite3.Row
            self._connection_pool.put(new_conn)
            raise
        else:
            # Only put the connection back if no exception occurred
            self._connection_pool.put(connection)

    def close(self):
        """Explicitly close all database connections in the pool"""
        try:
            # Create a list to track connections we've tried to close
            closed_connections = []
            
            # Try to get and close all connections in the pool
            while not self._connection_pool.empty():
                try:
                    conn = self._connection_pool.get(block=False)
                    closed_connections.append(conn)
                    conn.close()
                except Exception:
                    # If we can't get a connection, just continue
                    pass
                    
            # Log the number of connections closed
            logger.info(f"Closed {len(closed_connections)} database connections")
            
            # Reset the connection pool
            self._connection_pool = Queue(maxsize=10)
            
        except sqlite3.Error as e:
            logger.error(f"Error closing database connections: {e}")
        except Exception as e:
            logger.error(f"Unexpected error closing database connections: {e}")

    def execute_query(self, query: str, params: tuple = None) -> Optional[List[Dict]]:
        """Execute a SQL query with proper transaction handling"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute(query, params or ())
                
                # For INSERT queries, return the cursor to access lastrowid
                if query.strip().upper().startswith("INSERT"):
                    conn.commit()
                    return cur
                # For SELECT queries, return results as dictionaries
                elif query.strip().upper().startswith("SELECT"):
                    return [dict(row) for row in cur.fetchall()]
                # For other queries (UPDATE, DELETE), just commit
                else:
                    conn.commit()
                    return None
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Database query error: {e} | Query: {query}")
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
                event_uri TEXT,
                concepts TEXT,
                categories TEXT,
                location TEXT,
                extracted_dates TEXT,
                incident_sentence TEXT,
                event_type_uri TEXT,
                source_rank_percentile INTEGER,
                full_text TEXT,
                body_source TEXT,
                url_fallback_status TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (search_term_id) REFERENCES search_terms (id)
            )''',
            '''CREATE TABLE IF NOT EXISTS relevant_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_article_id INTEGER,
                relevance_score REAL CHECK (relevance_score >= 0 AND relevance_score <= 1),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                url_to_image TEXT,
                published_at TIMESTAMP NOT NULL,
                explanation TEXT,
                event TEXT,
                who_entities TEXT,
                where_location TEXT,
                impact TEXT,
                urgency TEXT,
                why_it_matters TEXT,
                incident_sentence TEXT,
                event_type_uri TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (raw_article_id) REFERENCES raw_articles (id)
            )''',
            '''CREATE TABLE IF NOT EXISTS processing_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_article_id INTEGER UNIQUE,
                relevance_score REAL CHECK (relevance_score >= 0 AND relevance_score <= 1),
                status TEXT NOT NULL CHECK (status IN ('relevant','irrelevant')),
                explanation TEXT,
                event TEXT,
                who_entities TEXT,
                where_location TEXT,
                impact TEXT,
                urgency TEXT,
                why_it_matters TEXT,
                incident_sentence TEXT,
                event_type_uri TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (raw_article_id) REFERENCES raw_articles (id)
            )'''
        ]

        with self.get_connection() as conn:
            cur = conn.cursor()
            try:
                for query in queries:
                    cur.execute(query)
                self._ensure_schema_columns(conn)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Error creating database tables: {e}")
                raise

    def _ensure_schema_columns(self, conn):
        """Best-effort migration for newly added optional columns."""
        optional_columns = {
            "raw_articles": {
                "event_uri": "TEXT",
                "concepts": "TEXT",
                "categories": "TEXT",
                "location": "TEXT",
                "extracted_dates": "TEXT",
                "incident_sentence": "TEXT",
                "event_type_uri": "TEXT",
                "source_rank_percentile": "INTEGER",
                "full_text": "TEXT",
                "body_source": "TEXT",
                "url_fallback_status": "TEXT",
            },
            "relevant_articles": {
                "explanation": "TEXT",
                "event": "TEXT",
                "who_entities": "TEXT",
                "where_location": "TEXT",
                "impact": "TEXT",
                "urgency": "TEXT",
                "why_it_matters": "TEXT",
                "incident_sentence": "TEXT",
                "event_type_uri": "TEXT",
            },
            "processing_results": {
                "explanation": "TEXT",
                "event": "TEXT",
                "who_entities": "TEXT",
                "where_location": "TEXT",
                "impact": "TEXT",
                "urgency": "TEXT",
                "why_it_matters": "TEXT",
                "incident_sentence": "TEXT",
                "event_type_uri": "TEXT",
            },
        }

        cur = conn.cursor()
        for table, columns in optional_columns.items():
            cur.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            for column, column_def in columns.items():
                if column not in existing:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")

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

    def insert_article(self, article_data: dict, search_term_id: Optional[int] = None) -> Optional[int]:
        """
        Insert an article into the raw_articles table with improved error handling and field normalization.
        
        Args:
            article_data (dict): Dictionary containing article data with flexible field names
            search_term_id (Optional[int]): ID of associated search term, can also be in article_data
            
        Returns:
            Optional[int]: ID of inserted/existing article, None if operation fails
            
        Example:
            article_data = {
                'title': 'Article Title',
                'content': 'Article content',
                'url': 'https://example.com',
                'source': {'name': 'Source Name'} or 'Source Name',
                'url_to_image': 'image_url',
                'published_at': '2025-05-08'
            }
        """
        try:
            # Extract and normalize data with defaults for optional fields
            data = {
                'title': article_data.get('title', ''),
                'content': (
                    article_data.get('content', '')
                    or article_data.get('description', '')
                    or article_data.get('snippet', '')
                ),
                'url': article_data.get('url', ''),
                'search_term_id': search_term_id or article_data.get('search_term_id'),
                'published_at': (
                    article_data.get('published_at', '')
                    or article_data.get('publishedAt', '')
                    or article_data.get('published_on', '')
                ),
                'url_to_image': (
                    article_data.get('url_to_image', '')
                    or article_data.get('image_url', '')
                    or article_data.get('urlToImage', '')
                ),
                'event_uri': article_data.get('event_uri', ''),
                'concepts': article_data.get('concepts', ''),
                'categories': article_data.get('categories', ''),
                'location': article_data.get('location', ''),
                'extracted_dates': article_data.get('extracted_dates', ''),
                'incident_sentence': article_data.get('incident_sentence', ''),
                'event_type_uri': article_data.get('event_type_uri', ''),
                'source_rank_percentile': article_data.get('source_rank_percentile'),
                'full_text': article_data.get('full_text', ''),
                'body_source': article_data.get('body_source', ''),
                'url_fallback_status': article_data.get('url_fallback_status', ''),
            }
            
            # Process source field
            source = article_data.get('source', '') or article_data.get('source_name', '')
            data['source'] = source.get('name') if isinstance(source, dict) else str(source)

            # Normalize JSON-like metadata so sqlite gets a plain TEXT payload.
            for key in ['concepts', 'categories', 'location', 'extracted_dates']:
                if isinstance(data[key], (dict, list)):
                    data[key] = json.dumps(data[key], ensure_ascii=False)
            
            # Validate required fields
            if not all(data[key] for key in ['title', 'content', 'url']):
                logger.error(f"Missing required fields in article data: {data}")
                return None
                
            # Check if article already exists by URL
            existing = self.db_manager.execute_query(
                "SELECT id FROM raw_articles WHERE url = ?",
                (data['url'],)
            )
            
            if existing:
                logger.debug(f"Article already exists with URL: {data['url']}")
                return existing[0]['id']
            
            # Insert new article
            query = """
                INSERT INTO raw_articles 
                (title, content, source, url, url_to_image, published_at, search_term_id,
                 event_uri, concepts, categories, location, extracted_dates, incident_sentence,
                 event_type_uri, source_rank_percentile, full_text, body_source, url_fallback_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            values = (
                data['title'], data['content'], data['source'],
                data['url'], data['url_to_image'], data['published_at'],
                data['search_term_id'], data['event_uri'], data['concepts'],
                data['categories'], data['location'], data['extracted_dates'],
                data['incident_sentence'], data['event_type_uri'],
                data['source_rank_percentile'], data['full_text'],
                data['body_source'], data['url_fallback_status'],
            )
            
            result = self.db_manager.execute_query(query, values)
            if result and hasattr(result, 'lastrowid'):
                article_id = result.lastrowid
                logger.info(f"Successfully inserted article '{data['title']}' with ID {article_id}")
                return article_id
            else:
                logger.error("Failed to get lastrowid from insert operation")
                return None
                
        except Exception as e:
            logger.error(f"Error inserting article '{article_data.get('title', 'Unknown')}': {e}")
            return None

    def get_articles(self, article_id: Optional[int] = None) -> Optional[Dict]:
        """Retrieve articles with proper error handling"""
        try:
            query = "SELECT * FROM raw_articles WHERE id = ?" if article_id else \
                   "SELECT * FROM raw_articles ORDER BY published_at DESC"
            result = self.db_manager.execute_query(query, (article_id,) if article_id else None)
            return result[0] if article_id and result else result
        except sqlite3.Error as e:
            logger.error(f"Error retrieving articles: {e}")
            return None

    def get_article_by_id(self, article_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve an article from the raw_articles table by its ID."""
        query = "SELECT * FROM raw_articles WHERE id = ?"
        result = self.db_manager.execute_query(query, (article_id,))
        logger.info(f"get_article_by_id result: {result}")  
        # Return the first item if result exists, otherwise None
        return result[0] if result else None

    def insert_relevant_article(
        self,
        raw_article_id: int,
        title: str,
        content: str,
        source: str,
        url: str,
        url_to_image: str,
        published_at: str,
        relevance_score: float,
        explanation: str = "",
        event: str = "",
        who_entities: str = "",
        where_location: str = "",
        impact: str = "",
        urgency: str = "",
        why_it_matters: str = "",
        incident_sentence: str = "",
        event_type_uri: str = "",
    ) -> bool:
        """
        Insert an article into the relevant_articles table with duplication checking.
        
        Args:
            raw_article_id: ID of the raw article
            title: Article title
            content: Article content
            source: Article source
            url: Article URL (used for duplication checking)
            url_to_image: URL to article image
            published_at: Publication date
            relevance_score: Relevance score (0-1)
            
        Returns:
            bool: True if insertion was successful, False otherwise
        """
        try:
            # Check if article already exists in relevant_articles by URL
            existing = self.db_manager.execute_query(
                "SELECT id FROM relevant_articles WHERE url = ?",
                (url,)
            )
            
            if existing:
                logger.info(f"Article already exists in relevant_articles with URL: {url}")
                return True  # Consider it a success since the article is already there
                
            # Check if article already exists in relevant_articles by raw_article_id
            existing = self.db_manager.execute_query(
                "SELECT id FROM relevant_articles WHERE raw_article_id = ?",
                (raw_article_id,)
            )
            
            if existing:
                logger.info(f"Article already exists in relevant_articles with raw_article_id: {raw_article_id}")
                return True  # Consider it a success since the article is already there
            
            logger.info(f"Inserting relevant article with raw_article_id: {raw_article_id}")
            query = """
                INSERT INTO relevant_articles (
                    raw_article_id, title, content, source, url, 
                    url_to_image, published_at, relevance_score, explanation, event,
                    who_entities, where_location, impact, urgency, why_it_matters,
                    incident_sentence, event_type_uri
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                raw_article_id,
                title,
                content,
                source,
                url,
                url_to_image,
                published_at,
                relevance_score,
                explanation,
                event,
                who_entities,
                where_location,
                impact,
                urgency,
                why_it_matters,
                incident_sentence,
                event_type_uri,
            )
            self.db_manager.execute_query(query, params)
            return True
            
        except Exception as e:
            logger.error(f"Error inserting relevant article: {e}")
            return False
            
    def record_processing_result(
        self,
        raw_article_id: int,
        relevance_score: float,
        status: str,
        explanation: str = "",
        event: str = "",
        who_entities: str = "",
        where_location: str = "",
        impact: str = "",
        urgency: str = "",
        why_it_matters: str = "",
        incident_sentence: str = "",
        event_type_uri: str = "",
    ) -> bool:
        """Record processing outcome for any article, including irrelevants."""
        try:
            if status not in {"relevant", "irrelevant"}:
                logger.error(f"Invalid processing status '{status}' for article {raw_article_id}")
                return False

            query = """
                INSERT INTO processing_results (
                    raw_article_id, relevance_score, status, explanation, event,
                    who_entities, where_location, impact, urgency, why_it_matters,
                    incident_sentence, event_type_uri
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_article_id) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    status = excluded.status,
                    explanation = excluded.explanation,
                    event = excluded.event,
                    who_entities = excluded.who_entities,
                    where_location = excluded.where_location,
                    impact = excluded.impact,
                    urgency = excluded.urgency,
                    why_it_matters = excluded.why_it_matters,
                    incident_sentence = excluded.incident_sentence,
                    event_type_uri = excluded.event_type_uri,
                    processed_at = CURRENT_TIMESTAMP
            """
            self.db_manager.execute_query(
                query,
                (
                    raw_article_id,
                    relevance_score,
                    status,
                    explanation,
                    event,
                    who_entities,
                    where_location,
                    impact,
                    urgency,
                    why_it_matters,
                    incident_sentence,
                    event_type_uri,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Error recording processing result: {e}")
            return False

    def get_relevance_stats(self) -> Dict[str, int]:
        """Return counts of relevant/irrelevant articles."""
        try:
            rows = self.db_manager.execute_query(
                "SELECT status, COUNT(*) as count FROM processing_results GROUP BY status"
            ) or []
            stats = {row["status"]: row["count"] for row in rows}
            total = sum(stats.values())
            stats.setdefault("relevant", 0)
            stats.setdefault("irrelevant", 0)
            stats["total"] = total
            return stats
        except Exception as e:
            logger.error(f"Error fetching relevance stats: {e}")
            return {"relevant": 0, "irrelevant": 0, "total": 0}

    def get_processing_stats(self) -> Dict[str, Any]:
        """
        Return counts and max relevance score from processing_results.
        This is the canonical source of truth for analytics.
        """
        try:
            counts = self.db_manager.execute_query(
                "SELECT status, COUNT(*) as count FROM processing_results GROUP BY status"
            ) or []
            max_rows = self.db_manager.execute_query(
                "SELECT MAX(relevance_score) as max_score FROM processing_results"
            ) or [{"max_score": 0.0}]

            stats = {row["status"]: row["count"] for row in counts}
            total = sum(stats.values())
            stats.setdefault("relevant", 0)
            stats.setdefault("irrelevant", 0)
            stats["total"] = total
            stats["max_score"] = max_rows[0].get("max_score") or 0.0
            return stats
        except Exception as e:
            logger.error(f"Error fetching processing stats: {e}")
            return {"relevant": 0, "irrelevant": 0, "total": 0, "max_score": 0.0}

    # Keep the old method name for backward compatibility
    def insert_cleaned_article(self, raw_article_id: int, title: str, content: str, source: str, url: str, url_to_image: str, published_at: str, relevance_score: float) -> bool:
        """Legacy method that redirects to insert_relevant_article."""
        logger.warning("insert_cleaned_article is deprecated, use insert_relevant_article instead")
        return self.insert_relevant_article(raw_article_id, title, content, source, url, url_to_image, published_at, relevance_score)

    def update_article(self, article):
        """Update an existing article in the raw_articles table."""
        try:
            # Validate that the article has an ID
            if not article.get('id'):
                logger.error("Cannot update article without ID")
                return False
                
            query = """
                UPDATE raw_articles 
                SET title = ?, content = ?, source = ?, url = ?, url_to_image = ?, published_at = ?
                WHERE id = ?
            """
            
            # Extract source field properly
            source = article.get('source', 'Unknown Source')
            if isinstance(source, dict):
                source = source.get('name', 'Unknown Source')
                
            self.db_manager.execute_query(
                query,
                (
                    article.get('title', ''),
                    article.get('content', ''),
                    source,
                    article.get('url', ''),
                    article.get('url_to_image', ''),
                    article.get('published_at', ''),
                    article.get('id')
                )
            )
            logger.info(f"Updated article with ID: {article.get('id')}")
            return True
        except Exception as e:
            logger.error(f"Error updating article: {e}")
            return False

    def get_unanalyzed_count(self) -> int:
        """Get count of articles that haven't been analyzed for relevance yet."""
        try:
            query = """
                SELECT COUNT(*) as count FROM raw_articles 
                WHERE id NOT IN (SELECT raw_article_id FROM relevant_articles)
            """
            result = self.db_manager.execute_query(query)
            return result[0]['count'] if result else 0
        except Exception as e:
            logger.error(f"Error getting unanalyzed count: {e}")
            return 0

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

    def delete_search_term(self, term: str):
        """Delete a search term from the database."""
        try:
            with self.db_manager.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM search_terms WHERE term = ?", (term,))
                conn.commit()
            logger.info(f"✅ Successfully deleted search term '{term}'.")
        except sqlite3.Error as e:
            logger.error(f"❌ Error deleting search term '{term}': {e}")
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
        logger.error(f"Database initialization error: {e}")
        print(f"Error: {e}")

        exit(1)