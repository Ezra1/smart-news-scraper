import os
import sqlite3
import logging

def extract_cleaned_data(db_path: str, output_file: str):
    """Extract cleaned and relevant data from the database and save it to a .txt file."""
    conn = None  # Initialize conn to None
    try:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        query = """
        SELECT title, content, url FROM cleaned_articles
        WHERE relevance_score > 0.8
        """
        cursor.execute(query)
        articles = cursor.fetchall()

        with open(output_file, 'w') as file:
            for title, content, url in articles:
                file.write(f"Title: {title}\n")
                file.write(f"Content: {content}\n")
                file.write(f"URL: {url}\n")
                file.write("\n" + "="*80 + "\n\n")

        logging.info(f"Successfully extracted {len(articles)} articles to {output_file}")

    except FileNotFoundError as e:
        logging.error(f"File error: {e}")
        print(f"Error: {e}")
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        print(f"Error: {e}")
    except Exception as e:
        logging.error(f"Error: {e}")
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    db_path = "/home/turambar/projects/smart-news-scraper/data/smart_news.db"
    if not os.path.exists(db_path):
        logging.error(f"Database file not found: {db_path}")
        print(f"Error: Database file not found: {db_path}")
    else:
        output_file = "/home/turambar/projects/smart-news-scraper/output/cleaned_articles.txt"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        extract_cleaned_data(db_path, output_file)
