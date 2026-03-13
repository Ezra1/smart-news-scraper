from typing import List, Callable, Optional
from src.news_scraper import NewsArticleScraper
from src.candidate_filter import CandidateFilter
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
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        config_manager: Optional[ConfigManager] = None,
        scraper: Optional[NewsArticleScraper] = None,
        validator: Optional[ArticleValidator] = None,
    ):
        """
        Initialize the PipelineManager with database and configuration managers.

        Args:
            db_manager (DatabaseManager): Instance of database manager for data operations
            config_manager (ConfigManager): Instance of config manager for settings
            scraper (NewsArticleScraper, optional): Custom scraper for testing/overrides
            validator (ArticleValidator, optional): Custom validator for testing/overrides
        """
        self.db_manager = db_manager or DatabaseManager()
        self.config_manager = config_manager or ConfigManager()
        get_context = getattr(self.config_manager, "get_context_message", None)
        self.context_message = get_context() if callable(get_context) else {}
        # Default to no-op callbacks so headless/CLI usage does not raise
        self.progress_callback = lambda current, total: None
        self.status_callback = (
            lambda message, error=False, rate_limited=False, done=False: None
        )
        self.scraper = scraper or NewsArticleScraper(
            self.config_manager, db_manager=self.db_manager
        )
        self.candidate_filter = CandidateFilter(self.config_manager, db_manager=self.db_manager)
        self.processor = None
        self.validator = validator or ArticleValidator()
        self.cancelled = False  # Controlled via GUI stop button

    def cancel(self) -> None:
        """Signal the pipeline to stop as soon as possible."""
        self.cancelled = True
        if self.processor and hasattr(self.processor, "cancel"):
            self.processor.cancel()
        self.status_callback("Processing stopped by user", False, True, False)

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
        self.progress_callback = progress_callback or self.progress_callback
        self.status_callback = status_callback or self.status_callback

    def set_context_message(self, context_message: dict):
        """
        Update the ChatGPT context message used for article processing.

        Args:
            context_message (dict): New context message configuration for ChatGPT
        """
        self.context_message = context_message

    async def execute_pipeline(self, search_terms: List[dict], date_params: Optional[dict] = None):
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
            # Reset cancellation flag for a new run
            self.cancelled = False

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
            
            articles = await self.fetch_articles(terms, date_params=date_params)
            if self.cancelled:
                logger.warning("Pipeline cancelled during fetch stage")
                return []
            if not articles:
                return []
                
            cleaned = await self.clean_articles(articles)
            if self.cancelled:
                logger.warning("Pipeline cancelled during cleaning stage")
                return []
            if not cleaned:
                return []

            query_terms_by_id = {
                term.get("id"): term.get("term")
                for term in search_terms
                if isinstance(term, dict) and term.get("id") is not None and term.get("term")
            }
            filtered = self.filter_candidates(cleaned, query_terms_by_id=query_terms_by_id)
            if self.cancelled:
                logger.warning("Pipeline cancelled during candidate filtering stage")
                return []
            if not filtered:
                return []
                
            processed = await self.analyze_articles(filtered)
            return processed
            
        except ValueError as e:
            logger.error(f"Pipeline configuration error: {e}")
            raise
        except Exception as e:
            logger.error(f"Pipeline error: {str(e)}")
            raise

    async def fetch_articles(self, terms: List[str], date_params: Optional[dict] = None) -> List[dict]:
        """Fetch articles from news sources based on search terms."""
        try:
            self.status_callback("Starting article fetch...", False, False, False)
            all_articles = []
            total_terms = len(terms)
            articles_fetched = 0  # Add counter
            
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
                if self.cancelled:
                    logger.info("Fetch cancelled by user")
                    self.status_callback("Fetch stopped by user", False, True, False)
                    break
                self.status_callback(f"Processing term {current_term}/{total_terms}: {term} ({articles_fetched} articles found)", False, False, False)
                self.progress_callback(current_term, total_terms)
                
                # Pass single term to scraper
                term_articles = await self.scraper.fetch_articles(
                    [term],
                    {term: search_term_map.get(term)},
                    date_params=date_params,
                )
                
                # Check for rate limit after each term
                if self.scraper.rate_limited:
                    logger.warning(f"Rate limit reached after processing {current_term}/{total_terms} terms")
                    self.status_callback(f"Rate limit reached after finding {articles_fetched} articles. Moving to cleaning phase...", False, True, False)
                    break
                    
                if term_articles:
                    articles_fetched += len(term_articles)  # Update counter
                    all_articles.extend(term_articles)
                    logger.info(f"Found {len(term_articles)} articles for term '{term}' (Total: {articles_fetched})")

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
                if self.cancelled:
                    logger.info("Cleaning cancelled by user")
                    self.status_callback("Cleaning stopped by user", False, True, False)
                    break
                # Ensure ID is carried through
                article_id = article.get('id')
                if article_id is None:
                    logger.warning(f"Missing ID for article: {article.get('url', 'No URL')}")

                if clean_article := self.validator.clean_article(article):
                    clean_article['id'] = article_id  # Preserve the ID
                    cleaned.append(clean_article)

                # Report progress for cleaning phase
                self.progress_callback(i, total)
                self.status_callback(f"Cleaned {i}/{total} articles", False, False, False)

            self.status_callback(
                f"Completed cleaning {len(cleaned)}/{total} articles",
                False,
                False,
                True,
            )
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

            # Reset processor cancellation for this stage
            if hasattr(self.processor, "cancelled"):
                self.processor.cancelled = False

            # Forward progress from the processor to the callbacks
            self.processor.progress_callback = (
                lambda current, total: (
                    self.progress_callback(current, total),
                    self.status_callback(
                        f"Analyzed {current}/{total} articles", False, False, False
                    )
                )
            )

            # Ensure processor respects cancellation
            if hasattr(self.processor, "cancelled"):
                self.processor.cancelled = self.cancelled

            results = await self.processor.process_articles(articles)
            relevant_results = [
                r.article for r in results if getattr(r, "status", "") == "relevant" and getattr(r, "article", None)
            ]
            error_count = len([r for r in results if getattr(r, "status", "") == "error"])

            if self.cancelled:
                logger.info("Analysis cancelled by user")
                self.status_callback("Analysis stopped by user", False, True, False)
                return relevant_results

            summary_msg = f"Analyzed {len(results)} articles (relevant: {len(relevant_results)}, errors: {error_count})"
            self.status_callback(summary_msg, False, False, True)
            return relevant_results
        except Exception as e:
            self.status_callback(f"Analysis error: {str(e)}", True, False, False)
            raise

    def filter_candidates(self, articles: List[dict], query_terms_by_id: Optional[dict] = None) -> List[dict]:
        """Apply pre-LLM filtering funnel and report stage metrics."""
        self.status_callback("Filtering candidates before LLM...", False, False, False)
        filtered, stats = self.candidate_filter.filter_candidates(
            articles,
            query_terms_by_id=query_terms_by_id or {},
        )
        logger.info(
            "Pre-LLM funnel stats: retrieved=%s after_heuristics=%s after_semantic=%s sent_to_llm=%s drops=%s",
            stats.get("retrieved_count", 0),
            stats.get("after_heuristics_count", 0),
            stats.get("after_semantic_count", 0),
            stats.get("sent_to_llm_count", 0),
            stats.get("dropped_by_reason", {}),
        )
        self.status_callback(
            (
                "Candidate filtering complete: "
                f"{stats.get('sent_to_llm_count', 0)}/{stats.get('retrieved_count', 0)} sent to LLM"
            ),
            False,
            False,
            True,
        )
        return filtered
