import os
import json
import logging 
import logging.config
import re
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables from .env file
logging.config.fileConfig('logging.conf')
logger = logging.getLogger(__name__)
load_dotenv()


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self):
        self.db_name = os.getenv("DB_NAME")
        self.db_user = os.getenv("DB_USER")
        self.db_host = os.getenv("DB_HOST", "localhost")
        self.db_port = int(os.getenv("DB_PORT", "5432"))

    def get_connection(self):
        """Establish and return a connection to the PostgreSQL database."""
        try:
            connection = psycopg2.connect(
                dbname=self.db_name,
                user=self.db_user,
                host=self.db_host,
                port=self.db_port
            )
            return connection
        except psycopg2.Error as error:
            logging.error(f"Error connecting to the database: {error}")
            return None

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        """Execute a SQL query."""
        conn = self.get_connection()
        if not conn:
            logging.error("No connection to SQL database")
            return None
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    if fetch_one:
                        return cur.fetchone()
                    if fetch_all:
                        return cur.fetchall()
        except psycopg2.Error as error:
            logging.error(f"Database error: {error}")
        finally:
            conn.close()

def create_tables(self):
    table_names = {
        "search_terms": "search_terms",
        "raw_articles": "raw_articles",
        "cleaned_articles": "cleaned_articles",
        "images": "images"
    }

    """Create necessary tables in the database."""
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
            source VARCHAR(100),
            url VARCHAR(255),
            url_to_image VARCHAR(255),
            published_at TIMESTAMP,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {table_names["cleaned_articles"]} (
            id SERIAL PRIMARY KEY,
            raw_article_id INTEGER REFERENCES {table_names["raw_articles"]}(id) ON DELETE CASCADE,
            relevance_score FLOAT,
            title VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            source VARCHAR(100),
            url VARCHAR(255),
            url_to_image VARCHAR(255),
            published_at TIMESTAMP,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {table_names["images"]} (
            id SERIAL PRIMARY KEY,
            article_id INTEGER REFERENCES {table_names["cleaned_articles"]}(id) ON DELETE CASCADE,
            image_url VARCHAR(255) NOT NULL,
            detected_objects JSONB
        )
        """
    ]

    # Loop to execute commands and log the creation status
    for command in commands:
        try:
            self.execute_query(command)
            table_name = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', command).group(1)
            logging.info("Created table: %s", table_name)
        except Exception as error:
            logging.error("Error creating table: %s", error)
    
    print("Tables created successfully.")


class SearchTermManager:
    """Manages search terms in the database."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def refresh_search_terms(self, json_file_path):
        """Clear the search_terms table and populate it with data from a JSON file."""
        search_terms = self.load_search_terms_from_json(json_file_path)

        # Clear existing terms
        self.db_manager.execute_query("DELETE FROM search_terms;")
        logging.info("Cleared existing search terms.")

        # Insert new terms
        for term in search_terms:
            self.db_manager.execute_query(
                "INSERT INTO search_terms (term) VALUES (%s);", (term,)
            )
        logging.info(f"Inserted {len(search_terms)} new search terms.")

    @staticmethod
    def load_search_terms_from_json(json_file_path):
        """Load search terms from a JSON file."""
        try:
            with open(json_file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data.get("terms", [])
        except (IOError, json.JSONDecodeError) as error:
            logging.error(f"Error loading search terms from JSON: {error}")
            return []


class ArticleManager:
    """Manages articles in the database."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def insert_raw_article(self, search_term_id, title, content, source, url, url_to_image, published_at):
        """Insert a raw article into the database."""
        if published_at:
            published_at = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        query = """
            INSERT INTO raw_articles (search_term_id, title, content, source, url, url_to_image, published_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """
        return self.db_manager.execute_query(
            query,
            (search_term_id, title, content, source, url, url_to_image, published_at),
            fetch_one=True
        )

    def insert_cleaned_article(self, raw_article_id, title, content, source, url, url_to_image, published_at, relevance_score):
        """Insert a relevant article into the cleaned_articles table."""
        query = """
            INSERT INTO cleaned_articles (raw_article_id, title, content, source, url, url_to_image, published_at, relevance_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """
        self.db_manager.execute_query(
            query,
            (raw_article_id, title, content, source, url, url_to_image, published_at, relevance_score)
        )

    def get_articles(self, article_id=None):
        """Retrieve articles by ID or all articles."""
        if article_id:
            query = "SELECT * FROM raw_articles WHERE id = %s;"
            return self.db_manager.execute_query(query, (article_id,), fetch_one=True)
        query = "SELECT * FROM raw_articles;"
        return self.db_manager.execute_query(query, fetch_all=True)