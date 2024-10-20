import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database connection parameters
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", 5432)

def get_connection():
    """Establish and return a connection to the PostgreSQL database."""
    try:
        connection = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return connection
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        return None

def create_tables():
    """Create necessary tables in the database."""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS search_terms (
            id SERIAL PRIMARY KEY,
            term VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS raw_articles (
            id SERIAL PRIMARY KEY,
            search_term_id INTEGER REFERENCES search_terms(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            source VARCHAR(100),
            url VARCHAR(255),
            urlToImage VARCHAR(255),
            published_at TIMESTAMP,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cleaned_articles (
            id SERIAL PRIMARY KEY,
            raw_article_id INTEGER REFERENCES raw_articles(id) ON DELETE CASCADE,
            relevance_score FLOAT,
            title VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            source VARCHAR(100),
            url VARCHAR(255),
            urlToImage VARCHAR(255),
            published_at TIMESTAMP,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            article_id INTEGER REFERENCES cleaned_articles(id) ON DELETE CASCADE,
            image_url VARCHAR(255) NOT NULL,
            detected_objects JSONB -- Store detected objects from YOLO in JSON format
        )
        """
    )

    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            for command in commands:
                cur.execute(command)
            conn.commit()
            cur.close()
            print("Tables created successfully.")
        except Exception as e:
            print(f"Error creating tables: {e}")
        finally:
            conn.close()

def insert_search_term(term):
    """Insert a single search term into the search_terms table."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO search_terms (term) VALUES (%s) RETURNING id;
            """, (term,))
            search_term_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            return search_term_id
        except Exception as e:
            print(f"Error inserting search term '{term}': {e}")
        finally:
            conn.close()
    return None

def get_search_terms():
    """Retrieve all search terms from the search_terms table."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, term FROM search_terms;")
            search_terms = cur.fetchall()
            cur.close()
            return search_terms
        except Exception as e:
            print(f"Error retrieving search terms: {e}")
        finally:
            conn.close()
    return []
