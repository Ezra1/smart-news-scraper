"""src/database.py"""

import os
import json
import logging 
import logging.config
import re
import datetime
from typing import Optional, List, Dict
from .cache import QueryCache
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from dotenv import load_dotenv
from .duplication import ArticleDeduplicator
from .validation import ArticleValidator

# Get the absolute path to the logging.conf and search_terms.json files
current_directory = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')
search_terms_path = os.path.join(current_directory, '..', "config", "search_terms.json")

# Set up logging
logging.config.fileConfig(logging_config_path)
logger = logging.getLogger(__name__)
load_dotenv()


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self):
        self.db_name = os.getenv("DB_NAME")
        self.db_user = os.getenv("DB_USER")
        self.db_host = os.getenv("DB_HOST", "localhost")
        self.db_port = int(os.getenv("DB_PORT", "5432"))
        self.min_connections = int(os.getenv("DB_MIN_CONNECTIONS", "1"))
        self.max_connections = int(os.getenv("DB_MAX_CONNECTIONS", "10"))
        
        self.pool = SimpleConnectionPool(
            self.min_connections,
            self.max_connections,
            dbname=self.db_name,
            user=self.db_user,
            host=self.db_host,
            port=self.db_port
        )
        self.cache = QueryCache()

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool using context manager."""
        conn = self.pool.getconn()
        try:
            yield conn
        finally:
            self.pool.putconn(conn)

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        """Execute a SQL query with caching."""
        if params is None:
            params = tuple()
        else:
            params = tuple(params)

        # Only cache SELECT queries
        if query.strip().upper().startswith('SELECT'):
            cached_result = self.cache.get(query, params)
            if cached_result is not None:
                return cached_result

        # Execute query if no cache hit
        with self.get_connection() as conn:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    if fetch_one:
                        result = cur.fetchone()
                    elif fetch_all:
                        result = cur.fetchall()
                    else:
                        result = None

                    # Cache the result for SELECT queries
                    if query.strip().upper().startswith('SELECT'):
                        self.cache.set(query, params, result)
                    
                    return result

    def create_tables(self):
        """Create necessary tables in the database."""
        table_names = {
            "search_terms": "search_terms",
            "raw_articles": "raw_articles",
            "cleaned_articles": "cleaned_articles",
            "images": "images"
        }

        commands = [
            f"""
            CREATE TABLE IF NOT EXISTS {table_names["search_terms"]} (
                id SERIAL PRIMARY KEY,
                term VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {table_names["raw_articles"]} (
                id SERIAL PRIMARY KEY,
                search_term_id INTEGER REFERENCES {table_names["search_terms"]}(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                source VARCHAR(100) NOT NULL,
                url VARCHAR(2048) NOT NULL UNIQUE,  -- Standard maximum URL length
                url_to_image VARCHAR(2048),
                published_at TIMESTAMP NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {table_names["cleaned_articles"]} (
                id SERIAL PRIMARY KEY,
                raw_article_id INTEGER REFERENCES {table_names["raw_articles"]}(id) ON DELETE CASCADE,
                relevance_score FLOAT CHECK (relevance_score >= 0 AND relevance_score <= 1),
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                source VARCHAR(100) NOT NULL,
                url VARCHAR(2048) NOT NULL UNIQUE,
                url_to_image VARCHAR(2048),
                published_at TIMESTAMP NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS {table_names["images"]} (
                id SERIAL PRIMARY KEY,
                article_id INTEGER REFERENCES {table_names["cleaned_articles"]}(id) ON DELETE CASCADE,
                image_url VARCHAR(2048) NOT NULL,
                detected_objects JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]

        success = True
        for command in commands:
            try:
                self.execute_query(command)
                match = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', command)
                if match:
                    table_name = match.group(1)
                    logging.info("Created table: %s", table_name)
                else:
                    logging.warning("Could not find table name in command: %s", command)
            except Exception as error:
                success = False
                logging.error("Error creating table: %s", error)
                raise  # Re-raise the exception to handle it at a higher level

        if success:
            logging.info("All tables created successfully")
            print("Tables created successfully.")
        else:
            logging.error("Failed to create all tables")
            print("Error occurred while creating tables. Check logs for details.")


class SearchTermManager:
    """Manages search terms in the database."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def get_search_terms(self):
        query = "SELECT id, term FROM search_terms;"
        return self.db_manager.execute_query(query, fetch_all=True)

    def refresh_search_terms(self):
        try: 
            """Clear the search_terms table and populate it with data from a JSON file."""
            search_terms = self.load_search_terms_from_json(search_terms_path)

            # Clear existing terms
            self.db_manager.execute_query("DELETE FROM search_terms;")
            logging.info("Cleared existing search terms.")

            # Insert new terms
            for term in search_terms:
                self.db_manager.execute_query(
                    "INSERT INTO search_terms (term) VALUES (%s);", (term,)
                )
            logging.info(f"Inserted {len(search_terms)} new search terms.")
        except Exception as error:
            logging.error("Error refreshing search terms: %s", error)

    @staticmethod
    def load_search_terms_from_json(json_file_path):
        """Load search terms from a JSON file."""
        try:
            with open(json_file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data.get("terms", [])
        except (IOError, json.JSONDecodeError) as error:
            logging.error("Error loading search terms from JSON: %s", error)
            return []


class ArticleManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.deduplicator = ArticleDeduplicator()
        self.validator = ArticleValidator()

    def article_exists(self, url: str, database: str = "raw_articles") -> bool:
        """
        Check if an article with the given URL exists in the specified database.
        
        Args:
            url (str): The URL of the article to check
            database (str): The database table to check ('raw_articles' or 'cleaned_articles')
        
        Returns:
            bool: True if the article exists, False otherwise
        """
        try:
            query = f"""
                SELECT EXISTS (
                    SELECT 1 
                    FROM {database} 
                    WHERE url = %s
                );
            """
            result = self.db_manager.execute_query(query, (url,), fetch_one=True)
            return result.get('exists', False) if result else False
            
        except Exception as error:
            logging.error(f"Error checking article existence in {database}: {error}")
            return False
    
    def insert_article(self, article_data: dict, search_term_id: int, database: str) -> Optional[int]:
        """Insert article after checking for duplicates."""
        try:
            cleaned_data = self.validator.clean_article(article_data)
            if not cleaned_data:
                logging.warning(f"Article validation failed: {article_data.get('title')}")
                return None
            # Get recent articles and check for duplicates
            recent_articles = self.get_recent_articles(days=7)
            if recent_articles and self.deduplicator.find_duplicates([article_data] + recent_articles):
                logging.info(f"Duplicate content detected for article: {article_data.get('title')}")
                return None

            # Process timestamp
            published_at = None
            if article_data.get('published_at'):
                published_at = datetime.datetime.fromisoformat(
                    article_data['published_at'].replace("Z", "+00:00")
                )

            # Validate required fields
            required_fields = ['title', 'content', 'source_name', 'url']
            if not all(article_data.get(field) for field in required_fields):
                logging.warning(f"Missing required fields in article: {article_data.get('title')}")
                return None

            query = """
                INSERT INTO {} 
                (search_term_id, title, content, source, url, url_to_image, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE 
                SET 
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    published_at = EXCLUDED.published_at
                RETURNING id;
            """.format(database)

            article_id = self.db_manager.execute_query(
                query,
                (
                    search_term_id,
                    article_data.get('title'),
                    article_data.get('content'),
                    article_data.get('source_name'),
                    article_data.get('url'),
                    article_data.get('url_to_image'),
                    published_at
                ),
                fetch_one=True
            )
            
            if article_id:
                logging.info(f"Successfully inserted/updated article: {article_data.get('title')}")
                return article_id['id']
            return None

        except Exception as error:
            logging.error(f"Error inserting article into {database}: {error}")
            return None

    def get_recent_articles(self, days: int = 7) -> List[Dict]:
        """Get articles from the last N days."""
        query = """
            SELECT * FROM raw_articles 
            WHERE published_at >= NOW() - INTERVAL '%s days'
            ORDER BY published_at DESC;
        """
        return self.db_manager.execute_query(query, (days,), fetch_all=True) or []

    def get_articles(self, article_id: Optional[int] = None) -> Optional[Dict]:
        """Get single article by ID or all articles."""
        try:
            if article_id:
                query = "SELECT * FROM raw_articles WHERE id = %s;"
                return self.db_manager.execute_query(query, (article_id,), fetch_one=True)
            
            query = "SELECT * FROM raw_articles ORDER BY published_at DESC;"
            return self.db_manager.execute_query(query, fetch_all=True)
            
        except Exception as error:
            logging.error(f"Error retrieving articles: {error}")
            return None

    def delete_article(self, article_id: int) -> bool:
        """Delete an article by ID."""
        try:
            query = "DELETE FROM raw_articles WHERE id = %s RETURNING id;"
            result = self.db_manager.execute_query(query, (article_id,), fetch_one=True)
            return bool(result)
        except Exception as error:
            logging.error(f"Error deleting article {article_id}: {error}")
            return False

    def __del__(self):
        """Cleanup database connections."""
        if hasattr(self.db_manager, 'pool'):
            self.db_manager.pool.closeall()