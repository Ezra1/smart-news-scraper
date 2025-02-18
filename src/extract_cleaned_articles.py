import os
import sqlite3
import sys
from pathlib import Path

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from src.logger_config import setup_logging
from src.config import ConfigManager 
logger = setup_logging(__name__)

def extract_cleaned_data(db_path: str, output_file: str):
    """Extract cleaned and relevant data from the database and save it to a .txt file."""
    conn = None  # Initialize conn to None
    try:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")

        # Get the relevance threshold from config
        config_manager = ConfigManager()
        relevance_threshold = config_manager.get("RELEVANCE_THRESHOLD", 0.7)
        logger.info(f"Using relevance threshold from config: {relevance_threshold}")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        query = """
        SELECT title, content, url, relevance_score FROM cleaned_articles
        WHERE relevance_score >= ?
        ORDER BY relevance_score DESC
        """
        cursor.execute(query, (relevance_threshold,))
        articles = cursor.fetchall()

        with open(output_file, 'w', encoding='utf-8') as file:
            file.write(f"Articles with relevance score >= {relevance_threshold}:\n\n")
            for title, content, url, score in articles:
                file.write(f"Relevance Score: {score}\n")
                file.write(f"Title: {title}\n")
                file.write(f"Content: {content}\n")
                file.write(f"URL: {url}\n")
                file.write("\n" + "="*80 + "\n\n")

        logger.info(f"Successfully extracted {len(articles)} articles to {output_file}")
        print(f"Exported {len(articles)} articles with relevance score >= {relevance_threshold}")

    except FileNotFoundError as e:
        logger.error(f"File error: {e}")
        print(f"Error: {e}")
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        print(f"Error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Get user's desktop path
    desktop_path = str(Path.home() / "Desktop")
    output_file = str(Path(desktop_path) / "cleaned_articles.txt")
    
    # Fix the database path construction
    project_root = Path(__file__).resolve().parent.parent
    db_path = str(project_root / "news_articles.db")
    
    if not os.path.exists(db_path):
        logger.error(f"Database file not found: {db_path}")
        print(f"Error: Database file not found: {db_path}")
    else:
        logger.info(f"Exporting cleaned articles to desktop: {output_file}")
        extract_cleaned_data(db_path, output_file)
