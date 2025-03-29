from typing import List, Callable
from src.news_scraper import NewsArticleScraper
from src.openai_relevance_processing import ArticleProcessor
from src.article_validator import ArticleValidator
from src.database_manager import DatabaseManager
from src.config import ConfigManager
from src.logger_config import setup_logging

logger = setup_logging(__name__)

class PipelineManager:
    def __init__(self, db_manager: DatabaseManager, config_manager: ConfigManager):
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.scraper = NewsArticleScraper(config_manager)
        self.processor = ArticleProcessor(db_manager)
        self.validator = ArticleValidator()
        self._progress_callback = None
        self._status_callback = None

    def set_callbacks(self, progress_callback: Callable[[int, int], None],
                     status_callback: Callable[[str, bool, bool, bool], None]):
        """Set callbacks for progress and status updates"""
        self._progress_callback = progress_callback
        self._status_callback = status_callback

    async def execute_pipeline(self, search_terms: List[dict]):
        """Handles the complete pipeline execution"""
        try:
            terms = [term['term'] for term in search_terms if isinstance(term, dict) and 'term' in term]
            logger.info(f"Processing search terms: {terms}")
            
            articles = await self.fetch_articles(terms)
            if not articles:
                return []
                
            cleaned = await self.clean_articles(articles)
            if not cleaned:
                return []
                
            processed = await self.analyze_articles(cleaned)
            return processed
            
        except Exception as e:
            logger.error(f"Pipeline error: {str(e)}")
            raise

    async def fetch_articles(self, terms: List[str]) -> List[dict]:
        """Execute fetch phase"""
        try:
            self._status_callback("Fetching articles...", False, False, False)
            articles = await self.scraper.fetch_articles(terms)
            
            # If rate limited or no articles, try getting from database
            if not articles or self.scraper.rate_limited:
                self._status_callback("Rate limit reached. Using existing articles...", False, True, False)
                articles = self.db_manager.execute_query("""
                    SELECT 
                        ra.id,
                        ra.search_term_id,
                        ra.title,
                        ra.content,
                        ra.source,
                        ra.url,
                        ra.url_to_image,
                        ra.published_at,
                        ra.scraped_at
                    FROM raw_articles ra
                """)
                logger.info(f"Retrieved {len(articles)} articles from database")
            
            # Ensure all articles have an ID
            for article in articles:
                if 'id' not in article:
                    logger.warning(f"Article missing ID: {article.get('url', 'No URL')}")
                else:
                    logger.debug(f"Processing article with ID: {article['id']}")
            
            total = len(articles)
            self._progress_callback(total, total)
            self._status_callback(f"Found {total} articles to process", False, False, True)
            
            return articles
        except Exception as e:
            self._status_callback(f"Fetch error: {str(e)}", True, False, False)
            raise

    async def clean_articles(self, articles: List[dict]) -> List[dict]:
        """Execute clean phase"""
        try:
            self._status_callback("Cleaning articles...", False, False, False)
            cleaned = []
            total = len(articles)
            
            for i, article in enumerate(articles, 1):
                # Ensure ID is carried through
                article_id = article.get('id')
                if article_id is None:
                    logger.warning(f"Missing ID for article: {article.get('url', 'No URL')}")
                
                if clean_article := self.validator.clean_article(article):
                    clean_article['id'] = article_id  # Preserve the ID
                    cleaned.append(clean_article)
                self._progress_callback(i, total)
            
            self._status_callback(f"Cleaned {len(cleaned)} articles", False, False, True)
            return cleaned
        except Exception as e:
            self._status_callback(f"Clean error: {str(e)}", True, False, False)
            raise

    async def analyze_articles(self, articles: List[dict]) -> List[dict]:
        """Execute analyze phase"""
        try:
            self._status_callback("Analyzing articles...", False, False, False)
            results = await self.processor.process_articles(articles)
            self._status_callback(f"Analyzed {len(results)} articles", False, False, True)
            return results
        except Exception as e:
            self._status_callback(f"Analysis error: {str(e)}", True, False, False)
            raise
