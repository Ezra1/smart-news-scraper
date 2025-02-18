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
                      to enhance supply chain security and prevent counterfeit medications. 
                      The system includes end-to-end tracking of drug shipments and 
                      temperature monitoring for sensitive medications. This initiative 
                      aims to reduce the $200 billion counterfeit drug market.''',
            'url': 'https://example.com/pharma-security',
            'source': 'Test Source',
            'published_at': datetime.now().isoformat()
        }
        
        # Insert test article
        cursor = db.connection.cursor()
        cursor.execute("""
            INSERT INTO raw_articles (title, content, url, source, published_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            test_article['title'],
            test_article['content'],
            test_article['url'],
            test_article['source'],
            test_article['published_at']
        ))
        db.connection.commit()
        test_article['id'] = cursor.lastrowid

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
            
            print("\nRelevance Analysis:")
            print("="*80)
            print(f"Relevant articles: {relevance_filter.relevant}")
            print(f"Irrelevant articles: {relevance_filter.irrelevant}")
            print(f"Max relevance score: {relevance_filter.max_relevance_score}")
            print("="*80)
        else:
            print("\n❌ Article processing failed")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
    finally:
        # Clean up test data
        cursor.execute("DELETE FROM raw_articles WHERE id = ?", (test_article['id'],))
        db.connection.commit()
        db.close()

if __name__ == "__main__":
    asyncio.run(test_process_single_article())