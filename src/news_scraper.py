import aiohttp
import asyncio
from typing import List, Dict
from pathlib import Path
import sys

from src.logger_config import setup_logging
logger = setup_logging(__name__)

# Add project root to Python path for imports
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.config import ConfigManager

class NewsArticleScraper:
    """
    A class to handle asynchronous news article fetching with rate limiting and error handling.
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
        
    async def fetch_articles(self, search_term: str) -> List[Dict]:
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
            
            # Implement rate limiting between requests
            await asyncio.sleep(1/self.config.get("NEWS_API_REQUESTS_PER_SECOND", 1))
            
            # Fetch articles for the current term
            articles = await self.fetch_articles(term['term'])
            self.partial_results.append(term['term'])  # Track progress
            
            # Add search term ID to each article and add to results
            if articles:
                for article in articles:
                    article['search_term_id'] = term['id']
                all_articles.extend(articles)

        return all_articles