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

from src.database_manager import DatabaseManager, ArticleManager
from src.openai_relevance_processing import ArticleProcessor
from src.insert_processed_articles import RelevanceFilter

async def test_process_single_article():
    """Test processing a single article and display the results."""
    try:
        # Get database connection
        db = DatabaseManager("news_articles.db")
        article_manager = ArticleManager(db)
        
        # Create a relevant test article
        test_article = {
            'title': 'New Pharmaceutical Supply Chain Security Measures Implemented',
            'content': '''Major pharmaceutical companies have implemented blockchain technology 
                      to enhance supply chain security and prevent counterfeit medications.''',
            'url': 'https://example.com/pharma-security',
            'source': {'name': 'Test Source'},  # Use dict format for source
            'published_at': datetime.now().isoformat()
        }
        
        article_id = article_manager.insert_article(test_article)
        test_article['id'] = article_id

        print("\n" + "="*80)
        print("Testing Article:")
        print("="*80)
        print(f"ID: {test_article['id']}")
        print(f"Title: {test_article['title']}")
        print(f"Content preview: {test_article['content'][:200]}...")
        print("="*80)

        # Process the article
        processor = ArticleProcessor()
        result = await processor.process_article(test_article, remaining_articles=0)
        
        if result:
            print("\nProcessing Result:")
            print("="*80)
            print(json.dumps(result, indent=2))
            print("="*80)
            
            # Initialize RelevanceFilter and process the result
            relevance_filter = RelevanceFilter(article_manager)
            relevance_filter.process_result(result)
            
            # Use the common analysis interface
            analysis_results = relevance_filter.analyze_results()
            
            print("\nRelevance Analysis:")
            print("="*80)
            for key, value in analysis_results.items():
                print(f"{key}: {value}")
            print("="*80)
        else:
            print("\n❌ Article processing failed")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
    finally:
        # Clean up test data using the proper DatabaseManager interface
        if 'test_article' in locals() and 'id' in test_article:
            try:
                db.execute_query("DELETE FROM raw_articles WHERE id = ?", (test_article['id'],))
                print(f"Cleaned up test article with ID: {test_article['id']}")
            except Exception as e:
                print(f"Error cleaning up test article: {e}")
        
        # Close database connection using the manager's method
        if db:
            db.close()
            print("Database connection closed")

if __name__ == "__main__":
    asyncio.run(test_process_single_article())