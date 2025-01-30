import aiohttp
import logging
from typing import List, Dict
from config import ConfigManager

logger = logging.getLogger(__name__)

class NewsArticleScraper:
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.api_key = self.config.get("NEWS_API_KEY")
        self.api_url = self.config.get("NEWS_API_URL")
        self.rate_limited = False
        
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
        all_articles = []
        for term in search_terms:
            if self.rate_limited:
                break
            articles = await self.fetch_articles(term['term'])
            for article in articles:
                article['search_term_id'] = term['id']
            all_articles.extend(articles)
        return all_articles