import aiohttp
import asyncio
from typing import List, Dict
from pathlib import Path
import sys

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
        
    async def _fetch_for_term(self, search_term: str) -> List[Dict]:
        """
        Fetch articles for a single search term using NewsAPI.
        
        Args:
            search_term: The term to search for in news articles
            
        Returns:
            List[Dict]: List of article dictionaries from the API response
        """
        try:
            # Create a new aiohttp session for the request
            async with aiohttp.ClientSession() as session:
                # Set up the API request parameters
                params = {
                    'q': search_term,
                    'apiKey': self.api_key,
                    'language': 'en',
                    'sortBy': 'publishedAt'
                }
                
                # Make the API request
                async with session.get(self.api_url, params=params) as response:
                    if response.status == 200:
                        # Successful response
                        data = await response.json()
                        return data.get('articles', [])
                    elif response.status == 429:
                        # Rate limit exceeded
                        self.rate_limited = True
                        logger.warning("Rate limit reached. Skipping remaining terms.")
                        return []
                    else:
                        # Other API errors
                        logger.error(f"API request failed: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching articles: {e}")
            return []

    async def fetch_articles(self, search_terms: List[str], search_term_map: Dict[str, int]) -> List[Dict]:
        """Fetch articles for given search terms with proper database insertion"""
        all_articles = []
        
        for term in search_terms:
            try:
                params = {
                    'q': term,
                    'apiKey': self.api_key,
                    'language': 'en',
                    'sortBy': 'publishedAt'
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.api_url, params=params) as response:
                        if response.status == 429:  # Rate limit hit
                            self.rate_limited = True
                            logger.warning("Rate limit reached")
                            break
                            
                        data = await response.json()
                        if data.get('status') == 'ok':
                            articles = data.get('articles', [])
                            
                            # Insert each article with its search term ID
                            for article in articles:
                                search_term_id = search_term_map.get(term)
                                if search_term_id:
                                    # Add search term ID to article data
                                    article['search_term_id'] = search_term_id
                                    inserted_id = self.article_manager.insert_article(article, search_term_id)
                                    if inserted_id:
                                        article['id'] = inserted_id
                                        all_articles.append(article)
                                        
                            logger.info(f"Fetched {len(articles)} articles for term '{term}'")
                        else:
                            logger.error(f"API error: {data.get('message', 'Unknown error')}")
                            
            except Exception as e:
                logger.error(f"Error fetching articles for term '{term}': {e}")
                continue
                
        return all_articles

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