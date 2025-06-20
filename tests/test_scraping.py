import pytest
import asyncio
from unittest.mock import Mock, patch
from src.news_scraper import NewsArticleScraper

class MockConfigManager:
    def get(self, key, default=None):
        config = {
            "NEWS_API_KEY": "test_api_key",
            "NEWS_API_URL": "http://test.api/v2/everything",
            "NEWS_API_REQUESTS_PER_SECOND": 1
        }
        return config.get(key, default)

@pytest.fixture
def scraper():
    return NewsArticleScraper(MockConfigManager())

@pytest.mark.asyncio
async def test_scraper_initialization(scraper):
    assert scraper.api_key == "test_api_key"
    assert scraper.api_url == "http://test.api/v2/everything"
    assert not scraper.rate_limited
    assert scraper.partial_results == []

@pytest.mark.asyncio
async def test_fetch_for_term_success():
    mock_response = {
        "status": "ok",
        "articles": [
            {"title": "Test Article 1", "description": "Test Description 1"},
            {"title": "Test Article 2", "description": "Test Description 2"}
        ]
    }
    
    with patch('aiohttp.ClientSession') as mock_session:
        mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 200
        mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.json = asyncio.coroutine(lambda: mock_response)
        
        scraper = NewsArticleScraper(MockConfigManager())
        articles = await scraper._fetch_for_term("test")
        
        assert len(articles) == 2
        assert articles[0]["title"] == "Test Article 1"
        assert articles[1]["title"] == "Test Article 2"

@pytest.mark.asyncio
async def test_fetch_for_term_rate_limit():
    with patch('aiohttp.ClientSession') as mock_session:
        mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 429
        
        scraper = NewsArticleScraper(MockConfigManager())
        articles = await scraper._fetch_for_term("test")
        
        assert len(articles) == 0
        assert scraper.rate_limited == True
