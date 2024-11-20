import json
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file (for database connection)
load_dotenv()

# Database connection parameters
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", 5432)

# Connect to the PostgreSQL database
def get_connection():
    """Establish and return a connection to the PostgreSQL database."""
    try:
        connection = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            host=DB_HOST,
            port=DB_PORT
        )
        return connection
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        return None

# Insert a single search term into the search_terms table
def insert_search_term(term):
    """Insert a single search term into the database."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO search_terms (term)
                VALUES (%s);
            """, (term,))
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"Error inserting term '{term}': {e}")
        finally:
            conn.close()

# Load search terms from JSON file and insert into database
def insert_search_terms_from_json(json_file):
    """Insert search terms from a JSON file into the search_terms table."""
    try:
        # Open and load the JSON file
        with open(json_file, 'r') as f:
            data = json.load(f)
            terms = data.get('terms', [])
            
            # Insert each term into the database
            for term in terms:
                insert_search_term(term)
            print(f"Successfully inserted {len(terms)} search terms.")
    except Exception as e:
        print(f"Error processing the JSON file: {e}")

# Specify the JSON file containing the search terms
json_file = 'search_terms.json'

# Insert the search terms into the database
insert_search_terms_from_json(json_file)
