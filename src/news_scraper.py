import aiohttp
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import sys

from src.database_manager import ArticleManager, DatabaseManager
from src.logger_config import setup_logging
logger = setup_logging(__name__)

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.config import ConfigManager

class NewsArticleScraper:
    """
    A class to handle asynchronous news article fetching with error handling.
    Interfaces with NewsAPI to fetch articles based on search terms.
    """
    
    def __init__(self, config_manager: ConfigManager):
        """
        Initialize the scraper with configuration settings.
        
        Args:
            config_manager: ConfigManager instance containing API keys and settings
        """
        self.config = config_manager
        self.api_key = self.config.get("NEWS_API_KEY")
        self.api_url = self.config.get("NEWS_API_URL")
        self.rate_limited = False  # Flag to track API rate limit status
        self.partial_results = []  # Track processed search terms for resume capability
        
        # Initialize database components
        self.db_manager = DatabaseManager()
        self.article_manager = ArticleManager(self.db_manager)
        
        # Rate limiting settings
        self.requests_per_second = config_manager.get("NEWS_API_REQUESTS_PER_SECOND", 1)
        self._last_request_time = 0
        
    async def fetch_articles(self, search_terms: List[str], search_term_map: Dict[str, int]) -> List[dict]:
        """Fetch articles for given search terms."""
        all_articles = []
        self.rate_limited = False
        
        for term in search_terms:
            try:
                await self._wait_for_rate_limit()
                
                # Handle multi-language search by removing language restriction
                # and using both original and English variations
                params = {
                    "q": term,
                    "apiKey": self.api_key,
                    "sortBy": "relevancy",  # Changed from publishedAt to get most relevant results
                    "pageSize": 100,
                    "from": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    "to": datetime.now().strftime("%Y-%m-%d"),
                    "searchIn": "title,description,content"  # Explicitly set search fields
                }
                
                # Try without language restriction first
                articles = await self._make_api_request(params)
                if not articles:
                    # If no results, try with English
                    params["language"] = "en"
                    articles = await self._make_api_request(params)
                
                # Process and store articles
                for article in articles:
                    article_data = {
                        "title": article.get("title"),
                        "content": article.get("content") or article.get("description", ""),
                        "source": article.get("source", {}).get("name"),
                        "url": article.get("url"),
                        "url_to_image": article.get("urlToImage"),
                        "published_at": article.get("publishedAt"),
                        "search_term_id": search_term_map.get(term)
                    }
                    
                    article_id = self.article_manager.insert_raw_article(**article_data)
                    if article_id:
                        article_data["id"] = article_id
                        all_articles.append(article_data)
                
                logger.info(f"Fetched {len(articles)} articles for term '{term}'")
                
            except Exception as e:
                logger.error(f"Error fetching articles for term '{term}': {str(e)}")
                
        return all_articles

    async def _make_api_request(self, params: dict) -> List[dict]:
        """Make request to NewsAPI with error handling."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("articles", [])
                    elif response.status == 429:
                        logger.warning("Rate limit exceeded")
                        self.rate_limited = True
                        return []
                    else:
                        response_text = await response.text()
                        logger.error(f"API request failed with status {response.status}")
                        logger.error(f"Response: {response_text}")
                        return []
        except Exception as e:
            logger.error(f"API request error: {e}")
            return []

    async def _wait_for_rate_limit(self):
        """Implement rate limiting."""
        current_time = datetime.now().timestamp()
        time_since_last = current_time - self._last_request_time
        if time_since_last < (1.0 / self.requests_per_second):
            await asyncio.sleep((1.0 / self.requests_per_second) - time_since_last)
        self._last_request_time = datetime.now().timestamp()

    async def fetch_all_articles(self, search_terms: List[Dict]) -> List[Dict]:
        """
        Fetch articles for multiple search terms with rate limiting and error handling.
        
        Args:
            search_terms: List of dictionaries containing search terms and their IDs
            
        Returns:
            List[Dict]: Combined list of articles from all search terms
        """
        all_articles = []
        for term in search_terms:
            # Check if we've hit the rate limit
            if self.rate_limited:
                logger.warning(f"Rate limit reached after processing {len(all_articles)} articles.")
                logger.warning(f"Skipping remaining {len(search_terms) - len(self.partial_results)} terms.")
                return all_articles
            
            # Fetch articles for the current term
            articles = await self._fetch_for_term(term['term'])
            self.partial_results.append(term['term'])  # Track progress
            
            # Add search term ID to each article and add to results
            if articles:
                for article in articles:
                    article['search_term_id'] = term['id']
                all_articles.extend(articles)

        return all_articles