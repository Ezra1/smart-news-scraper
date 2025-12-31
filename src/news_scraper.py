import aiohttp
import asyncio
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from src.database_manager import ArticleManager, DatabaseManager
from src.logger_config import setup_logging
logger = setup_logging(__name__)

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.config import ConfigManager
from src.utils.rate_limiter import RateLimiter

class NewsArticleScraper:
    """
    A class to handle asynchronous news article fetching with error handling.
    Interfaces with The News API to fetch articles based on search terms.
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
        requests_per_second = config_manager.get("NEWS_API_REQUESTS_PER_SECOND", 1)
        self.rate_limiter = RateLimiter(requests_per_second=requests_per_second)
        
    async def fetch_articles(self, search_terms: List[str], search_term_map: Dict[str, int]) -> List[dict]:
        """
        Fetch and process articles for multiple search terms.
        
        Args:
            search_terms: List of search terms
            search_term_map: Mapping of search terms to their database IDs
            
        Returns:
            List[dict]: Processed and stored articles
        """
        all_articles = []
        self.rate_limited = False
        
        for term in search_terms:
            try:
                # Fetch raw articles for the term
                raw_articles = await self._fetch_for_term(term)

                if self.rate_limited:
                    break

                # Process and store articles
                for article in raw_articles:
                    combined_content = article.get("content") or article.get("description", "")
                    if not combined_content:
                        snippet = article.get("snippet")
                        if snippet:
                            combined_content = snippet
                    if article.get("description") and article.get("snippet"):
                        combined_content = f"{article.get('description')}\n\n{article.get('snippet')}"
                    if not combined_content:
                        combined_content = article.get("title", "")
                    article_data = {
                        "title": article.get("title"),
                        "content": combined_content,
                        "description": article.get("description"),
                        "snippet": article.get("snippet"),
                        "source": article.get("source", {}),
                        "url": article.get("url"),
                        "url_to_image": article.get("urlToImage"),
                        "image_url": article.get("image_url"),
                        "published_at": article.get("published_at"),
                        "publishedAt": article.get("publishedAt"),
                        "search_term_id": search_term_map.get(term)
                    }

                    article_id = self.article_manager.insert_article(article_data)
                    if article_id:
                        article_data["id"] = article_id
                        all_articles.append(article_data)
                        
                logger.info(f"Processed {len(raw_articles)} articles for term '{term}'")
                    
            except Exception as e:
                logger.error(f"Error processing articles for term '{term}': {str(e)}")
                
        return all_articles

    
    async def _fetch_for_term(self, term: str) -> List[Dict]:
        """
        Fetch articles for a single search term from the news API.
        
        Args:
            term (str): The search term to query for
            
        Returns:
            List[Dict]: List of article dictionaries containing metadata and content
        """
        logger.info(f"Fetching articles for term: {term}")
        
        try:
            now_utc = datetime.now(timezone.utc)
            thirty_days_ago = now_utc - timedelta(days=30)
            # The News API accepts several precise date formats without a trailing 'Z'.
            # Use UTC and seconds precision: YYYY-MM-DDTHH:MM:SS
            def format_dt(dt: datetime) -> str:
                return dt.replace(microsecond=0, tzinfo=None).isoformat(timespec="seconds")
            published_after_val = format_dt(thirty_days_ago)
            published_before_val = format_dt(now_utc)

            all_articles: List[Dict] = []
            per_page_limit = 50
            max_pages = 5  # safety cap to avoid excessive calls

            for page in range(1, max_pages + 1):
                await self._wait_for_rate_limit()

                params = {
                    "search": term,
                    "api_token": self.api_key,
                    "limit": per_page_limit,
                    "page": page,
                    # The News API supports search across defaults; avoid unsupported fields
                    # that can trigger malformed_parameter responses.
                    "language": "en",
                    "published_after": published_after_val,
                    "published_before": published_before_val,
                }

                page_articles = await self._make_api_request(params)

                if not page_articles:
                    break

                all_articles.extend(page_articles)

                # If fewer than the requested limit were returned, no more pages.
                if len(page_articles) < per_page_limit:
                    break

            logger.info(f"Found {len(all_articles)} articles for term: {term}")
            return all_articles
            
        except Exception as e:
            logger.error(f"Error fetching articles for term '{term}': {str(e)}")
            return []

    async def _make_api_request(self, params: dict) -> List[dict]:
        """Make request to The News API with error handling."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        articles = data.get("data", [])
                        if isinstance(articles, dict):
                            flattened: List[Dict[str, Any]] = []
                            for value in articles.values():
                                if isinstance(value, list):
                                    flattened.extend(value)
                            return flattened
                        return articles or []
                    elif response.status == 429:
                        logger.warning("Rate limit exceeded")
                        self.rate_limited = True
                        return []
                    elif response.status == 401:
                        logger.error("Invalid The News API token")
                        return []
                    else:
                        response_text = await response.text()
                        logger.error(
                            "API request failed with status %s | params=%s | response=%s",
                            response.status,
                            params,
                            response_text,
                        )
                        return []
        except Exception as e:
            logger.error(f"API request error: {e}")
            return []

    async def _wait_for_rate_limit(self):
        """Implement rate limiting."""
        await self.rate_limiter.wait_if_needed_async()

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
