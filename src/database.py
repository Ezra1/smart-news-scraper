import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
import json


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

# Load search terms from JSON file
def load_search_terms_from_json(json_file_path):
    """Load search terms from a JSON file."""
    try:
        with open(json_file_path, 'r') as file:
            data = json.load(file)
            return data.get("terms", [])
    except Exception as e:
        print(f"Error loading search terms from JSON: {e}")
        return []

# Function to clear the search_terms table and populate it with JSON data
def refresh_search_terms():
    """Clear the search_terms table and populate it with data from config/search_terms.json."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Clear the search_terms table
            cur.execute("DELETE FROM search_terms;")
            conn.commit()
            print("Cleared existing search terms.")

            # Load new search terms from JSON
            json_file_path = os.path.join("config", "search_terms copy.json")
            search_terms = load_search_terms_from_json(json_file_path)
            
            # Insert each search term into the database
            for term in search_terms:
                cur.execute("""
                    INSERT INTO search_terms (term) VALUES (%s);
                """, (term,))
            conn.commit()
            print(f"Inserted {len(search_terms)} new search terms.")

            cur.close()
        except Exception as e:
            print(f"Error refreshing search terms: {e}")
        finally:
            conn.close()

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

def is_win1252_compatible(text):
    """Check if a text string is compatible with Win-1252 encoding."""
    try:
        text.encode('cp1252')
        return True
    except UnicodeEncodeError:
        return False

def filter_non_win1252_chars(text):
    """Filter out non-Windows-1252 characters from a text string."""
    return text.encode('cp1252', errors='ignore').decode('cp1252')

def insert_raw_article(search_term_id, title, content, source, url, urlToImage, published_at):
    """Insert a raw article into the raw_articles table, checking for Win-1252 compatibility."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Convert published_at to datetime if it's in ISO format
            if published_at:
                published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            
            # Check Win-1252 compatibility for title and content
            if not is_win1252_compatible(title):
                title = filter_non_win1252_chars(title)
            if not is_win1252_compatible(content):
                content = filter_non_win1252_chars(content)
            
            # Insert the article into the raw_articles table
            cur.execute("""
                INSERT INTO raw_articles (search_term_id, title, content, source, url, urlToImage, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
            """, (search_term_id, title, content, source, url, urlToImage, published_at))
            
            article_id = cur.fetchone()[0]  # Get the ID of the inserted article
            conn.commit()
            cur.close()
            return article_id
        except Exception as e:
            print(f"Error inserting raw article: {e}")
        finally:
            conn.close()
    return None

def get_articles(article_id=None):
    """
    Retrieve article(s) from the raw_articles table. 
    If article_id is provided, retrieve a single article; otherwise, retrieve all articles.
    """
    conn = get_connection()
    articles = []

    if conn:
        try:
            cur = conn.cursor()
            if article_id is not None:
                # Retrieve a single article by ID
                cur.execute("""
                    SELECT id, title, content, source, url, urltoimage, published_at
                    FROM raw_articles
                    WHERE id = %s;
                """, (article_id,))
                row = cur.fetchone()
                if row:
                    articles.append({
                        "id": row[0],
                        "title": row[1],
                        "content": row[2],
                        "source": row[3],
                        "url": row[4],
                        "urltoimage": row[5],
                        "published_at": row[6]
                    })
            else:
                # Retrieve all articles
                cur.execute("SELECT id, title, content, source, url, urltoimage, published_at FROM raw_articles;")
                rows = cur.fetchall()
                for row in rows:
                    articles.append({
                        "id": row[0],
                        "title": row[1],
                        "content": row[2],
                        "source": row[3],
                        "url": row[4],
                        "urltoimage": row[5],
                        "published_at": row[6]
                    })
            cur.close()
        except Exception as e:
            print(f"Error fetching article(s): {e}")
        finally:
            conn.close()

    # Return a single dictionary if only one article was requested, otherwise return a list
    return articles[0] if article_id and articles else articles


def insert_cleaned_article(raw_article_id, title, content, source, url, urlToImage, published_at, relevance_score):
    """Insert a relevant article into the cleaned_articles table."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Insert into cleaned_articles
            cur.execute("""
                INSERT INTO cleaned_articles (raw_article_id, title, content, source, url, urltoimage, published_at, relevance_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (raw_article_id, title, content, source, url, urlToImage, published_at, relevance_score))
            
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"Error inserting cleaned article: {e}")
        finally:
            conn.close()
