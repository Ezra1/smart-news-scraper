from typing import Any, Dict, List, Callable, Optional
import time
from src.news_scraper import NewsArticleScraper
from src.candidate_filter import CandidateFilter
from src.openai_relevance_processing import ArticleProcessor
from src.article_validator import ArticleValidator
from src.database_manager import DatabaseManager
from src.config import ConfigManager
from src.logger_config import setup_logging
from src.query_expander import build_settings, expand_terms_to_queries
from src.request_budget import apply_budget_to_queries, resolve_request_budget
from src.pipeline_result import AnalysisPhaseResult, PipelineRunResult

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
        self._last_fetch_meta: Dict[str, Any] = {}
        self._last_pre_llm_stats: Dict[str, Any] = {}

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

    def _return_if_cancelled(
        self, stage_name: str, run_metrics: Optional[Dict[str, Any]] = None
    ) -> Optional[PipelineRunResult]:
        """Return an empty result when pipeline cancellation is requested."""
        if not self.cancelled:
            return None
        logger.warning("Pipeline cancelled during %s stage", stage_name)
        return PipelineRunResult(
            completed_successfully=False,
            completion_detail=f"Cancelled during {stage_name}",
            run_metrics=dict(run_metrics or {}),
        )

    def _snapshot_effective_settings(self, date_params: Optional[dict]) -> Dict[str, Any]:
        """Subset of config that materially affects a run (for GUI observability)."""
        cm = self.config_manager
        return {
            "RELEVANCE_THRESHOLD": float(cm.get("RELEVANCE_THRESHOLD", 0.7)),
            "PRELLM_ENABLE_FILTERING": bool(cm.get("PRELLM_ENABLE_FILTERING", False)),
            "PRELLM_FILTER_PRESET": str(cm.get("PRELLM_FILTER_PRESET", "more_permissive")),
            "PRELLM_ENABLE_LLM_GUARDRAIL": bool(cm.get("PRELLM_ENABLE_LLM_GUARDRAIL", False)),
            "MAXIMUM_RECALL_MODE": bool(cm.get("MAXIMUM_RECALL_MODE", False)),
            "HIGH_RECALL_MODE": bool(cm.get("HIGH_RECALL_MODE", True)),
            "QUERY_EXPANSION_ENABLED": bool(cm.get("QUERY_EXPANSION_ENABLED", True)),
            "QUERY_EXPANSION_USE_AI": bool(cm.get("QUERY_EXPANSION_USE_AI", True)),
            "QUERY_EXPANSION_LANGUAGES": str(cm.get("QUERY_EXPANSION_LANGUAGES", "en")),
            "QUERY_EXPANSION_VARIANTS_PER_TERM": int(cm.get("QUERY_EXPANSION_VARIANTS_PER_TERM", 3)),
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": int(cm.get("QUERY_EXPANSION_MAX_TOTAL_QUERIES", 120)),
            "REQUEST_BUDGET_MODE": str(cm.get("REQUEST_BUDGET_MODE", "aggressive")),
            "REQUEST_BUDGET_PER_RUN": int(cm.get("REQUEST_BUDGET_PER_RUN", 0)),
            "FETCH_MAX_ARTICLES_PER_RUN": int(cm.get("FETCH_MAX_ARTICLES_PER_RUN", 2000)),
            "FETCH_MAX_ARTICLES_PER_QUERY": int(cm.get("FETCH_MAX_ARTICLES_PER_QUERY", 500)),
            "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": int(
                cm.get("FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL", 20)
            ),
            "OPENAI_MAX_CONCURRENT_REQUESTS": int(cm.get("OPENAI_MAX_CONCURRENT_REQUESTS", 24)),
            "OPENAI_REQUESTS_PER_MINUTE": int(cm.get("OPENAI_REQUESTS_PER_MINUTE", 60)),
            "date_params": dict(date_params or {}),
        }

    @staticmethod
    def _top_counts(counter: Dict[str, int], limit: int = 10) -> List[Dict[str, Any]]:
        if not isinstance(counter, dict) or not counter:
            return []
        rows = [
            {"term": key, "count": int(value)}
            for key, value in counter.items()
            if isinstance(key, str) and key.strip()
        ]
        rows.sort(key=lambda row: (-row["count"], row["term"]))
        return rows[: max(1, int(limit))]

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / float(denominator), 4)

    @staticmethod
    def _dedupe_articles_by_url(articles: List[dict]) -> List[dict]:
        """Drop duplicate URLs (case-insensitive) while preserving order."""
        if not articles:
            return []
        seen: set[str] = set()
        out: List[dict] = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            url = str(article.get("url") or "").strip().lower()
            if not url:
                out.append(article)
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append(article)
        return out

    async def execute_pipeline(self, search_terms: List[dict], date_params: Optional[dict] = None):
        """
        Execute the complete article processing pipeline.

        Coordinates the fetch, clean, and analyze phases of article processing.
        Handles error reporting and ensures proper initialization of components.

        Args:
            search_terms (List[dict]): List of dictionaries containing search terms
                Each dict should have a 'term' key with the search string

        Returns:
            PipelineRunResult with relevant articles and analysis metrics.

        Raises:
            Exception: If any phase of the pipeline fails
        """
        if not isinstance(search_terms, list):
            raise ValueError("search_terms must be a list of term objects")
        if not search_terms:
            return PipelineRunResult(
                completion_detail="No search terms to process.",
                run_metrics={"effective_settings": self._snapshot_effective_settings(date_params)},
            )

        try:
            # Reset cancellation flag for a new run
            self.cancelled = False
            run_metrics: Dict[str, Any] = {
                "effective_settings": self._snapshot_effective_settings(date_params),
            }

            # Validate config before proceeding
            if not self.config_manager.validate():
                raise ValueError("Configuration validation failed - check API keys")

            effective_threshold = float(self.config_manager.get("RELEVANCE_THRESHOLD", 0.7))

            # Initialize processor with current config
            if not self.processor:
                self.processor = ArticleProcessor(
                    db_manager=self.db_manager,
                    context_message=self.context_message,
                    config_manager=self.config_manager
                )
                logger.info("Created new ArticleProcessor with current config")
            self.processor.RELEVANCE_THRESHOLD = effective_threshold

            terms = [term['term'] for term in search_terms if isinstance(term, dict) and 'term' in term]
            logger.info(f"Processing search terms: {terms}")
            
            articles = await self.fetch_articles(terms, date_params=date_params)
            run_metrics["fetch"] = dict(self._last_fetch_meta)
            run_metrics["fetch"]["unique_urls_returned"] = len(articles) if articles else 0

            cancelled_result = self._return_if_cancelled("fetch", run_metrics)
            if cancelled_result is not None:
                return cancelled_result
            if not articles:
                return PipelineRunResult(
                    completion_detail="No articles fetched.",
                    run_metrics=run_metrics,
                )

            cleaned = await self.clean_articles(articles)
            run_metrics["clean"] = {
                "input_count": len(articles),
                "output_count": len(cleaned),
                "dropped_invalid": max(0, len(articles) - len(cleaned)),
            }

            cancelled_result = self._return_if_cancelled("cleaning", run_metrics)
            if cancelled_result is not None:
                return cancelled_result
            if not cleaned:
                return PipelineRunResult(
                    completion_detail="No articles remained after cleaning.",
                    run_metrics=run_metrics,
                )

            query_terms_by_id = {
                term.get("id"): term.get("term")
                for term in search_terms
                if isinstance(term, dict) and term.get("id") is not None and term.get("term")
            }
            filtered = self.filter_candidates(cleaned, query_terms_by_id=query_terms_by_id)
            run_metrics["pre_llm"] = dict(self._last_pre_llm_stats)

            cancelled_result = self._return_if_cancelled("candidate filtering", run_metrics)
            if cancelled_result is not None:
                return cancelled_result
            if not filtered:
                return PipelineRunResult(
                    completion_detail="No articles passed candidate filtering.",
                    run_metrics=run_metrics,
                )

            analysis = await self.analyze_articles(filtered)
            success = not self.cancelled and analysis.error_count == 0
            detail = (
                f"Analyzed {analysis.analyzed_count} articles, "
                f"{len(analysis.relevant_articles)} relevant, {analysis.error_count} errors."
            )
            run_metrics["analyze"] = {
                "scored": analysis.analyzed_count,
                "relevant": len(analysis.relevant_articles),
                "errors": analysis.error_count,
            }
            fetched_count = int(run_metrics.get("fetch", {}).get("unique_urls_returned", 0))
            cleaned_count = int(run_metrics.get("clean", {}).get("output_count", 0))
            sent_to_llm = int(run_metrics.get("pre_llm", {}).get("sent_to_llm_count", 0))
            relevant_count = int(run_metrics["analyze"]["relevant"])
            run_metrics["funnel_rates"] = {
                "fetch_to_clean": self._safe_ratio(cleaned_count, fetched_count),
                "clean_to_pre_llm": self._safe_ratio(sent_to_llm, cleaned_count),
                "pre_llm_to_relevant": self._safe_ratio(relevant_count, sent_to_llm),
                "fetch_to_relevant": self._safe_ratio(relevant_count, fetched_count),
            }
            relevant_by_root: Dict[str, int] = {}
            for article in analysis.relevant_articles:
                if not isinstance(article, dict):
                    continue
                root_term = str(article.get("root_term") or "").strip()
                if not root_term:
                    continue
                relevant_by_root[root_term] = relevant_by_root.get(root_term, 0) + 1
            run_metrics["top_roots_by_relevant_count"] = self._top_counts(relevant_by_root, limit=10)
            return PipelineRunResult(
                relevant_articles=analysis.relevant_articles,
                articles_analyzed=analysis.analyzed_count,
                analysis_errors=analysis.error_count,
                completed_successfully=success,
                completion_detail=detail,
                run_metrics=run_metrics,
            )

        except ValueError as e:
            logger.error(f"Pipeline configuration error: {e}")
            raise
        except Exception as e:
            logger.error(f"Pipeline error: {str(e)}")
            raise

    async def fetch_articles(self, terms: List[str], date_params: Optional[dict] = None) -> List[dict]:
        """Fetch articles from news sources based on search terms."""
        self._last_fetch_meta = {}
        if terms is None:
            self.status_callback("Completed fetch: 0 articles from 0/0 terms", False, False, True)
            self._last_fetch_meta = {"error": "terms_is_none"}
            return []
        if not isinstance(terms, list):
            raise ValueError("terms must be a list")

        try:
            self.status_callback("Starting article fetch...", False, False, False)
            if not terms:
                self.status_callback("Completed fetch: 0 articles from 0/0 terms", False, False, True)
                self._last_fetch_meta = {
                    "root_terms_count": 0,
                    "queries_planned": 0,
                    "queries_completed": 0,
                }
                return []
            all_articles = []
            total_terms = len(terms)
            articles_fetched = 0  # Add counter
            terms_processed = 0

            # Get search term IDs before fetching
            search_term_map = {}
            for term in terms:
                result = self.db_manager.execute_query(
                    "SELECT id FROM search_terms WHERE term = ?",
                    (term,)
                )
                if result:
                    search_term_map[term] = result[0]['id']

            expansion_settings = build_settings(self.config_manager)
            expansion_diagnostics: Dict[str, Any] = {}
            expanded_queries = expand_terms_to_queries(
                terms,
                expansion_settings,
                diagnostics=expansion_diagnostics,
            )
            if not expanded_queries:
                expanded_queries = [
                    type("QueryItem", (), {"term": term, "root_term": term, "language": "", "priority": idx})
                    for idx, term in enumerate(terms)
                ]

            budget = resolve_request_budget(
                mode=str(self.config_manager.get("REQUEST_BUDGET_MODE", "aggressive")),
                configured_budget=int(self.config_manager.get("REQUEST_BUDGET_PER_RUN", 0)),
            )
            if not bool(self.config_manager.get("HIGH_RECALL_MODE", True)):
                budget = min(budget, 50)
            if bool(self.config_manager.get("MAXIMUM_RECALL_MODE", False)):
                expanded_n = len(expanded_queries)
                if expanded_n > 0:
                    # Execute the full expanded plan (capped) instead of leaving queries unrunnable.
                    budget = max(budget, min(10000, expanded_n))
            planned_queries = apply_budget_to_queries(expanded_queries, budget)
            if not planned_queries:
                self.status_callback("Completed fetch: 0 articles from 0/0 terms", False, False, True)
                self._last_fetch_meta = {
                    "root_terms_count": total_terms,
                    "expanded_queries_count": len(expanded_queries),
                    "budget_resolved": budget,
                    "queries_planned": 0,
                    "queries_completed": 0,
                }
                return []

            # Process expanded queries one by one with progress tracking
            total_queries = len(planned_queries)
            fetched_by_root: Dict[str, int] = {}
            for current_term, query in enumerate(planned_queries, 1):
                terms_processed = current_term
                if self.cancelled:
                    logger.info("Fetch cancelled by user")
                    self.status_callback("Fetch stopped by user", False, True, False)
                    break
                self.status_callback(
                    (
                        f"Processing term {current_term}/{total_queries}: "
                        f"{query.term} [lang={query.language or 'default'}] "
                        f"({articles_fetched} articles found)"
                    ),
                    False,
                    False,
                    False,
                )
                self.progress_callback(current_term, total_queries)

                # Pass single expanded query to scraper
                term_articles = await self.scraper.fetch_articles(
                    [{
                        "term": query.term,
                        "root_term": query.root_term,
                        "language": query.language,
                    }],
                    {query.root_term: search_term_map.get(query.root_term)},
                    date_params=date_params,
                )
                
                # Check for rate limit after each term
                if self.scraper.rate_limited:
                    logger.warning(f"Rate limit reached after processing {current_term}/{total_queries} terms")
                    self.status_callback(f"Rate limit reached after finding {articles_fetched} articles. Moving to cleaning phase...", False, True, False)
                    break
                    
                if term_articles:
                    articles_fetched += len(term_articles)  # Update counter
                    all_articles.extend(term_articles)
                    root_key = str(query.root_term or query.term or "").strip()
                    if root_key:
                        fetched_by_root[root_key] = fetched_by_root.get(root_key, 0) + len(term_articles)
                    logger.info(
                        "Found %s articles for query '%s' (root '%s', lang=%s) total=%s",
                        len(term_articles),
                        query.term,
                        query.root_term,
                        query.language,
                        articles_fetched,
                    )

            rows_pre_dedup = len(all_articles)
            all_articles = self._dedupe_articles_by_url(all_articles)
            unique_after_dedup = len(all_articles)
            pre_cap = len(all_articles)
            max_run = max(1, int(self.config_manager.get("FETCH_MAX_ARTICLES_PER_RUN", 2000)))
            run_cap_applied = False
            if pre_cap > max_run:
                run_cap_applied = True
                logger.info(
                    "[FETCH] Run cap: keeping %s of %s unique URLs (FETCH_MAX_ARTICLES_PER_RUN)",
                    max_run,
                    pre_cap,
                )
                self.status_callback(
                    f"Capping fetched articles at {max_run} of {pre_cap} (run limit)...",
                    False,
                    False,
                    False,
                )
                all_articles = all_articles[:max_run]
            # Final status update
            articles_found = len(all_articles)
            self.status_callback(
                f"Completed fetch: {articles_found} articles from {terms_processed}/{total_queries} terms",
                False, False, True
            )
            self._last_fetch_meta = {
                "root_terms_count": total_terms,
                "expanded_queries_count": len(expanded_queries),
                "planned_queries_count": total_queries,
                "queries_planned": total_queries,
                "queries_completed": terms_processed,
                "budget_resolved": budget,
                "expansion_diagnostics": expansion_diagnostics,
                "rows_pre_url_dedup": rows_pre_dedup,
                "unique_urls_after_dedup": unique_after_dedup,
                "fetch_run_cap_applied": run_cap_applied,
                "unique_urls_final": articles_found,
                "rate_limited": bool(getattr(self.scraper, "rate_limited", False)),
                "top_roots_by_fetch_count": self._top_counts(fetched_by_root, limit=10),
            }
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
        if articles is None:
            return []
        if not isinstance(articles, list):
            raise ValueError("articles must be a list")
        if not articles:
            return []

        try:
            self.status_callback("Cleaning articles...", False, False, False)
            cleaned = []
            total = len(articles)
            slow_clean_threshold_seconds = 2.0
            
            for i, article in enumerate(articles, 1):
                if self.cancelled:
                    logger.info("Cleaning cancelled by user")
                    self.status_callback("Cleaning stopped by user", False, True, False)
                    break
                # Ensure ID is carried through
                article_id = article.get('id')
                if article_id is None:
                    logger.warning(f"Missing ID for article: {article.get('url', 'No URL')}")

                started = time.monotonic()
                if clean_article := self.validator.clean_article(article):
                    clean_article['id'] = article_id  # Preserve the ID
                    cleaned.append(clean_article)
                elapsed = time.monotonic() - started
                if elapsed >= slow_clean_threshold_seconds:
                    logger.warning(
                        "Slow cleaning for article %s/%s | id=%s url=%s elapsed=%.2fs",
                        i,
                        total,
                        article_id,
                        article.get("url", ""),
                        elapsed,
                    )

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

    async def analyze_articles(self, articles: List[dict]) -> AnalysisPhaseResult:
        """
        Analyze articles for relevance using the ArticleProcessor.

        Processes cleaned articles through ChatGPT to determine relevance
        and extract key information.

        Args:
            articles (List[dict]): Cleaned articles to analyze

        Returns:
            AnalysisPhaseResult with relevant articles and error counts.

        Raises:
            Exception: If article analysis fails
        """
        if articles is None:
            return AnalysisPhaseResult()
        if not isinstance(articles, list):
            raise ValueError("articles must be a list")
        if not articles:
            return AnalysisPhaseResult()
        if not self.processor:
            self.status_callback("Analysis error: processor is not initialized", True, False, False)
            return AnalysisPhaseResult()

        try:
            self.status_callback("Analyzing articles...", False, False, False)

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
                return AnalysisPhaseResult(
                    relevant_articles=relevant_results,
                    analyzed_count=len(results),
                    error_count=error_count,
                )

            summary_msg = f"Analyzed {len(results)} articles (relevant: {len(relevant_results)}, errors: {error_count})"
            self.status_callback(
                summary_msg,
                error_count > 0,
                False,
                True,
            )
            return AnalysisPhaseResult(
                relevant_articles=relevant_results,
                analyzed_count=len(results),
                error_count=error_count,
            )
        except Exception as e:
            self.status_callback(f"Analysis error: {str(e)}", True, False, False)
            raise

    def filter_candidates(self, articles: List[dict], query_terms_by_id: Optional[dict] = None) -> List[dict]:
        """Apply pre-LLM filtering funnel and report stage metrics."""
        if not isinstance(articles, list):
            logger.error("filter_candidates expected list articles, got %s", type(articles).__name__)
            return []
        if not articles:
            return []

        self.status_callback("Filtering candidates before LLM...", False, False, False)
        filtered, stats = self.candidate_filter.filter_candidates(
            articles,
            query_terms_by_id=query_terms_by_id or {},
        )
        self._last_pre_llm_stats = dict(stats) if isinstance(stats, dict) else {}
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
