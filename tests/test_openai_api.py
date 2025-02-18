"""Basic test for OpenAI article processing"""

import asyncio
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.database_manager import DatabaseManager
from src.openai_relevance_processing import ArticleProcessor

async def test_process_single_article():
    """Test processing a single article and display the results."""
    try:
        # Get database connection and fetch an article
        db = DatabaseManager("news_articles.db")
        articles = db.execute_query("SELECT * FROM raw_articles LIMIT 1")
        
        if not articles:
            print("❌ No articles found in database")
            return
            
        article = articles[0]
        print("\n" + "="*80)
        print("Testing Article:")
        print("="*80)
        print(f"ID: {article['id']}")
        print(f"Title: {article['title']}")
        print(f"Content preview: {article['content'][:200]}...")
        print("="*80)

        # Process the article
        processor = ArticleProcessor()
        result = await processor.process_article(article, remaining_articles=0)
        
        if result:
            print("\nProcessing Result:")
            print("="*80)
            print(json.dumps(result, indent=2))
            print("="*80)
        else:
            print("\n❌ Article processing failed")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_process_single_article())