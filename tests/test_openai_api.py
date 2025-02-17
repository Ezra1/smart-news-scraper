"""Basic tests for OpenAI API integration"""

import pytest
import os
import sys
import json
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
from src.database import DatabaseManager

def log_test(msg: str):
    """Simple test logging"""
    print(f"\n{msg}")

@pytest.fixture
def client():
    """Create OpenAI client"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not found")
    return OpenAI(api_key=api_key)

@pytest.fixture
def db_article():
    """Get first article from database"""
    db = DatabaseManager("news_articles.db")
    articles = db.execute_query("SELECT * FROM raw_articles LIMIT 1")
    if not articles:
        pytest.skip("No articles in database")
    return articles[0]

def test_api_connection(client):
    """Test OpenAI API connection"""
    log_test("Testing API connection")
    assert client is not None

def test_article_analysis(client, db_article):
    """Test article relevance analysis"""
    log_test(f"Testing article: {db_article['title'][:50]}...")
    
    response = client.chat.completions.create(
        model="gpt-4-turbo-preview",
        messages=[
            {
                "role": "system",
                "content": "Analyze pharmaceutical security and supply chain articles. Return JSON with relevance_score (0-1)."
            },
            {
                "role": "user",
                "content": f"Title: {db_article['title']}\nContent: {db_article['content']}"
            }
        ],
        max_tokens=250
    )
    
    result = response.choices[0].message.content
    log_test(f"API response: {result[:100]}...")
    
    # Basic response validation
    assert response.choices is not None
    assert len(response.choices) > 0
    
    # Try parsing JSON response
    try:
        json_data = json.loads(result)
        assert isinstance(json_data, dict)
        assert "relevance_score" in json_data
    except json.JSONDecodeError:
        # Fallback to keyword check if not JSON
        assert any(kw in result.lower() for kw in ['relevant', 'score', 'pharmaceutical'])

if __name__ == "__main__":
    pytest.main([__file__, "-v"])