from typing import List, Callable
from src.news_scraper import NewsArticleScraper
from src.openai_relevance_processing import ArticleProcessor
from src.article_validator import ArticleValidator
from src.database_manager import DatabaseManager
from src.config import ConfigManager
from src.logger_config import setup_logging

logger = setup_logging(__name__)

class PipelineManager:
    """
    Manages the complete pipeline for news article processing.

    This class orchestrates the entire workflow of fetching, cleaning, and analyzing news articles.
    It coordinates between different components including the news scraper, article validator,
    and article processor while managing database operations and status updates.

    Attributes:
        db_manager (DatabaseManager): Handles database operations
        config_manager (ConfigManager): Manages configuration settings
        context_message (dict): ChatGPT context message for article processing
        progress_callback (Callable): Callback for reporting progress updates
        status_callback (Callable): Callback for reporting status messages
        scraper (NewsArticleScraper): Handles article fetching
        processor (ArticleProcessor): Processes articles for relevance
        validator (ArticleValidator): Validates and cleans article data
    """
    def __init__(self, db_manager: DatabaseManager, config_manager: ConfigManager):
        """
        Initialize the PipelineManager with database and configuration managers.

        Args:
            db_manager (DatabaseManager): Instance of database manager for data operations
            config_manager (ConfigManager): Instance of config manager for settings
        """
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.context_message = config_manager.get("CHATGPT_CONTEXT_MESSAGE")
        self.progress_callback = None
        self.status_callback = None
        self.scraper = NewsArticleScraper(config_manager)
        self.processor = None
        self.validator = ArticleValidator()

    def set_callbacks(self, progress_callback: Callable[[int, int], None],
                     status_callback: Callable[[str, bool, bool, bool], None]):
        """
        Set callback functions for progress and status updates.

        Args:
            progress_callback (Callable[[int, int], None]): Function to report current progress
                First int is current count, second int is total count
            status_callback (Callable[[str, bool, bool, bool], None]): Function to report status
                Takes message string and three boolean flags for error, rate_limited, and done states
        """
        self.progress_callback = progress_callback
        self.status_callback = status_callback

    def set_context_message(self, context_message: dict):
        """
        Update the ChatGPT context message used for article processing.

        Args:
            context_message (dict): New context message configuration for ChatGPT
        """
        self.context_message = context_message

    async def execute_pipeline(self, search_terms: List[dict]):
        """
        Execute the complete article processing pipeline.

        Coordinates the fetch, clean, and analyze phases of article processing.
        Handles error reporting and ensures proper initialization of components.

        Args:
            search_terms (List[dict]): List of dictionaries containing search terms
                Each dict should have a 'term' key with the search string

        Returns:
            List[dict]: List of processed articles with relevance analysis
            
        Raises:
            Exception: If any phase of the pipeline fails
        """
        try:
            # Validate config before proceeding
            if not self.config_manager.validate():
                raise ValueError("Configuration validation failed - check API keys")

            # Initialize processor with current config
            if not self.processor:
                self.processor = ArticleProcessor(
                    db_manager=self.db_manager,
                    context_message=self.context_message,
                    config_manager=self.config_manager
                )
                logger.info("Created new ArticleProcessor with current config")

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
            
        except ValueError as e:
            logger.error(f"Pipeline configuration error: {e}")
            raise
        except Exception as e:
            logger.error(f"Pipeline error: {str(e)}")
            raise

    async def fetch_articles(self, terms: List[str]) -> List[dict]:
        """Fetch articles from news sources based on search terms."""
        try:
            self.status_callback("Starting article fetch...", False, False, False)
            all_articles = []
            total_terms = len(terms)
            
            # Get search term IDs before fetching
            search_term_map = {}
            for term in terms:
                result = self.db_manager.execute_query(
                    "SELECT id FROM search_terms WHERE term = ?",
                    (term,)
                )
                if result:
                    search_term_map[term] = result[0]['id']
            
            # Process terms one by one with progress tracking
            for current_term, term in enumerate(terms, 1):
                self.status_callback(f"Processing term {current_term}/{total_terms}: {term}", False, False, False)
                self.progress_callback(current_term, total_terms)
                
                # Pass single term to scraper
                term_articles = await self.scraper.fetch_articles([term], {term: search_term_map.get(term)})
                
                # Check for rate limit after each term
                if self.scraper.rate_limited:
                    logger.warning(f"Rate limit reached after processing {current_term}/{total_terms} terms")
                    self.status_callback("Rate limit reached. Moving to cleaning phase...", False, True, False)
                    break
                    
                if term_articles:
                    all_articles.extend(term_articles)
                    logger.info(f"Found {len(term_articles)} articles for term '{term}'")

            # Final status update
            articles_found = len(all_articles)
            terms_processed = current_term
            self.status_callback(
                f"Completed fetch: {articles_found} articles from {terms_processed}/{total_terms} terms", 
                False, False, True
            )
            return all_articles if articles_found > 0 else []
            
        except Exception as e:
            logger.error(f"Pipeline fetch error: {str(e)}")
            self.status_callback(f"Fetch error: {str(e)}", True, False, False)
            raise

    async def clean_articles(self, articles: List[dict]) -> List[dict]:
        """
        Clean and validate fetched articles.

        Processes each article through the validator to ensure data quality
        and consistency. Preserves article IDs during cleaning.

        Args:
            articles (List[dict]): Raw articles to clean

        Returns:
            List[dict]: List of cleaned and validated articles

        Raises:
            Exception: If article cleaning fails
        """
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
        """
        Analyze articles for relevance using the ArticleProcessor.

        Processes cleaned articles through ChatGPT to determine relevance
        and extract key information.

        Args:
            articles (List[dict]): Cleaned articles to analyze

        Returns:
            List[dict]: List of articles with relevance analysis results

        Raises:
            Exception: If article analysis fails
        """
        try:
            self.status_callback("Analyzing articles...", False, False, False)
            results = await self.processor.process_articles(articles)
            self.status_callback(f"Analyzed {len(results)} articles", False, False, True)
            return results
        except Exception as e:
            self.status_callback(f"Analysis error: {str(e)}", True, False, False)
            raise
