import aiohttp
import logging
import asyncio  # Add this import
from typing import List, Dict
from config import ConfigManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class NewsArticleScraper:
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.api_key = self.config.get("NEWS_API_KEY")
        self.api_url = self.config.get("NEWS_API_URL")
        self.rate_limited = False
        self.partial_results = []  # Add this line
        
    async def fetch_articles(self, search_term: str) -> List[Dict]:
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'q': search_term,
                    'apiKey': self.api_key,
                    'language': 'en',
                    'sortBy': 'publishedAt'
                }
                
                async with session.get(self.api_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('articles', [])
                    elif response.status == 429:
                        self.rate_limited = True
                        logger.warning("Rate limit reached. Skipping remaining terms.")
                        return []
                    else:
                        logger.error(f"API request failed: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching articles: {e}")
            return []

    async def fetch_all_articles(self, search_terms: List[Dict]) -> List[Dict]:
        """Fetch articles with improved rate limit handling."""
        all_articles = []
        for term in search_terms:
            if self.rate_limited:
                logger.warning(f"Rate limit reached after processing {len(all_articles)} articles.")
                logger.warning(f"Skipping remaining {len(search_terms) - len(self.partial_results)} terms.")
                return all_articles
            
            # Add delay between requests
            await asyncio.sleep(1/self.config.get("NEWS_API_REQUESTS_PER_SECOND", 1))
            
            articles = await self.fetch_articles(term['term'])
            self.partial_results.append(term['term'])  # Track processed terms
            
            if articles:
                for article in articles:
                    article['search_term_id'] = term['id']
                all_articles.extend(articles)

        return all_articles