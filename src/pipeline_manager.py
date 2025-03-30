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
        self.context_message = config_manager.get("CHATGPT_CONTEXT_MESSAGE")
        self.progress_callback = None
        self.status_callback = None
        self.scraper = NewsArticleScraper(config_manager)
        self.processor = None  # Initialize as None
        self.validator = ArticleValidator()

    def set_callbacks(self, progress_callback: Callable[[int, int], None],
                     status_callback: Callable[[str, bool, bool, bool], None]):
        """Set callbacks for progress and status updates"""
        self.progress_callback = progress_callback
        self.status_callback = status_callback

    def set_context_message(self, context_message: dict):
        """Update the ChatGPT context message"""
        self.context_message = context_message

    async def execute_pipeline(self, search_terms: List[dict]):
        """Handles the complete pipeline execution"""
        try:
            # Initialize processor here when needed
            if not self.processor:
                self.processor = ArticleProcessor(
                    db_manager=self.db_manager,
                    context_message=self.context_message
                )

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
            self.status_callback("Fetching articles...", False, False, False)
            
            # Get search term IDs before fetching
            search_term_map = {}
            for term in terms:
                result = self.db_manager.execute_query(
                    "SELECT id FROM search_terms WHERE term = ?",
                    (term,)
                )
                if result:
                    search_term_map[term] = result[0]['id']
            
            # Pass search term IDs to scraper
            articles = await self.scraper.fetch_articles(terms, search_term_map)
            
            # If rate limited or no articles, try getting from database
            if not articles or self.scraper.rate_limited:
                self.status_callback("Rate limit reached. Using existing articles...", False, True, False)
                articles = self.db_manager.execute_query(
                    "SELECT * FROM raw_articles WHERE search_term_id IN (SELECT id FROM search_terms WHERE term IN ({}))"
                    .format(','.join('?' * len(terms))), 
                    terms
                )
                logger.info(f"Retrieved {len(articles)} articles from database")

            # Update status with fetched count
            self.status_callback(f"Fetched {len(articles)} articles", False, False, True)
            
            total = len(articles)
            self.progress_callback(total, total)
            self.status_callback(f"Found {total} articles to process", False, False, True)
            
            return articles
            
        except Exception as e:
            logger.error(f"Pipeline fetch error: {str(e)}")
            self.status_callback(f"Fetch error: {str(e)}", True, False, False)
            raise

    async def clean_articles(self, articles: List[dict]) -> List[dict]:
        """Execute clean phase"""
        try:
            self.status_callback("Cleaning articles...", False, False, False)
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
                self.progress_callback(i, total)
            
            self.status_callback(f"Cleaned {len(cleaned)} articles", False, False, True)
            return cleaned
        except Exception as e:
            self.status_callback(f"Clean error: {str(e)}", True, False, False)
            raise

    async def analyze_articles(self, articles: List[dict]) -> List[dict]:
        """Execute analyze phase"""
        try:
            self.status_callback("Analyzing articles...", False, False, False)
            results = await self.processor.process_articles(articles)
            self.status_callback(f"Analyzed {len(results)} articles", False, False, True)
            return results
        except Exception as e:
            self.status_callback(f"Analysis error: {str(e)}", True, False, False)
            raise
