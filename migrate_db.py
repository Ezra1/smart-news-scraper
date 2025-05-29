#!/usr/bin/env python3
"""
Database migration script to rename cleaned_articles to relevant_articles.
This script will:
1. Create the relevant_articles table if it doesn't exist
2. Copy data from cleaned_articles to relevant_articles
3. Drop the cleaned_articles table
"""

import os
import sqlite3
import sys
from pathlib import Path

from src.logger_config import setup_logging
logger = setup_logging(__name__)

def migrate_database(db_path: str):
    """Migrate the database to use relevant_articles instead of cleaned_articles."""
    conn = None
    try:
        if not os.path.exists(db_path):
            logger.error(f"Database file not found: {db_path}")
            print(f"Error: Database file not found: {db_path}")
            return False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if cleaned_articles table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cleaned_articles'")
        cleaned_exists = cursor.fetchone() is not None

        # Check if relevant_articles table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='relevant_articles'")
        relevant_exists = cursor.fetchone() is not None

        if not cleaned_exists and relevant_exists:
            logger.info("Migration already completed. Only relevant_articles table exists.")
            print("Migration already completed. Only relevant_articles table exists.")
            return True

        if not cleaned_exists and not relevant_exists:
            logger.info("No migration needed. Neither table exists.")
            print("No migration needed. Neither table exists.")
            return True

        # Create relevant_articles table if it doesn't exist
        if not relevant_exists:
            logger.info("Creating relevant_articles table...")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS relevant_articles (
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

        # Copy data from cleaned_articles to relevant_articles if cleaned_articles exists
        if cleaned_exists:
            logger.info("Copying data from cleaned_articles to relevant_articles...")
            
            # Get column names from cleaned_articles
            cursor.execute("PRAGMA table_info(cleaned_articles)")
            columns = [column[1] for column in cursor.fetchall()]
            column_names = ", ".join(columns)
            
            # Copy data
            cursor.execute(f"""
                INSERT OR IGNORE INTO relevant_articles ({column_names})
                SELECT {column_names} FROM cleaned_articles
            """)
            conn.commit()
            
            # Check how many rows were copied
            cursor.execute("SELECT COUNT(*) FROM cleaned_articles")
            cleaned_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM relevant_articles")
            relevant_count = cursor.fetchone()[0]
            
            logger.info(f"Copied {relevant_count} of {cleaned_count} rows from cleaned_articles to relevant_articles")
            print(f"Copied {relevant_count} of {cleaned_count} rows from cleaned_articles to relevant_articles")
            
            # Drop the cleaned_articles table
            logger.info("Dropping cleaned_articles table...")
            cursor.execute("DROP TABLE cleaned_articles")
            conn.commit()
            
            logger.info("Migration completed successfully")
            print("Migration completed successfully")
            return True
            
    except sqlite3.Error as e:
        logger.error(f"Database error during migration: {e}")
        print(f"Error: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        print(f"Error: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Get database path
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        project_root = Path(__file__).resolve().parent
        db_path = str(project_root / "news_articles.db")
    
    print(f"Migrating database: {db_path}")
    success = migrate_database(db_path)
    
    if success:
        print("Migration completed successfully")
        sys.exit(0)
    else:
        print("Migration failed")
        sys.exit(1)