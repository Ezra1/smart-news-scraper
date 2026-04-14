import os
import sys
import time
import asyncio
import logging  # Add this import for logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from openai import OpenAI, LengthFinishReasonError, RateLimitError
from pydantic import BaseModel

from src.logger_config import setup_logging
logger = setup_logging(__name__)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from src.database_manager import ArticleManager, DatabaseManager
from src.config import ConfigManager
from src.analysis_base import ArticleAnalysisMixin
from src.utils.rate_limiter import RateLimiter
from src.utils.article_normalization import extract_source_name
from src.incident_filter import should_skip_llm, is_incident_article

class RatedArticle(BaseModel):
    """Structured output schema for processed articles."""
    relevance_score: float
    explanation: str = ""
    event: str = ""
    who_entities: str = ""
    where_location: str = ""
    impact: str = ""
    urgency: str = ""
    why_it_matters: str = ""
    confidence_notes: str = ""


@dataclass
class ProcessingResult:
    """Result wrapper so callers can distinguish success, irrelevance, and errors."""
    article: Optional[Dict[str, Any]]
    status: str  # 'relevant', 'irrelevant', or 'error'
    error: Optional[str] = None

class ArticleProcessor(ArticleAnalysisMixin):
    def __init__(self, db_manager: DatabaseManager = None, 
                 context_message: dict = None,
                 config_manager: ConfigManager = None):
        super().__init__()  # Initialize analysis mixin
        self.config_manager = config_manager or ConfigManager()
        self.OPENAI_API_KEY = self.config_manager.get("OPENAI_API_KEY")
        
        if not self.OPENAI_API_KEY:
            logger.error("Missing OpenAI API Key in configuration")
            raise ValueError("OpenAI API Key is required. Please configure it in the Configuration tab.")
        
        self.client = OpenAI(api_key=self.OPENAI_API_KEY)
        requests_per_minute = self.config_manager.get("OPENAI_REQUESTS_PER_MINUTE", 60)
        self.rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
        max_concurrent = int(self.config_manager.get("OPENAI_MAX_CONCURRENT_REQUESTS", 24) or 24)
        max_concurrent = max(1, min(64, max_concurrent))
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # Initialize tracking variables
        self.relevant = 0
        self.irrelevant = 0
        self.total_relevant = 0  # Will be kept in sync with self.relevant
        self.max_relevance_score = 0.0
        self.RELEVANCE_THRESHOLD = self.config_manager.get("RELEVANCE_THRESHOLD")
        logger.info(f"Initialized ArticleProcessor with relevance threshold: {self.RELEVANCE_THRESHOLD}")
        
        # Use provided database manager or create new one
        self.db_manager = db_manager or DatabaseManager()
        self.article_manager = ArticleManager(self.db_manager)
        
        # Add batch size configuration
        self.batch_size = self.config_manager.get("BATCH_SIZE", 10)
        maximum_recall = bool(self.config_manager.get("MAXIMUM_RECALL_MODE", False))
        self.enable_llm_guardrail = bool(
            self.config_manager.get("PRELLM_ENABLE_LLM_GUARDRAIL", True)
        ) and not maximum_recall
        self.relevance_max_tokens = max(256, int(self.config_manager.get("OPENAI_RELEVANCE_MAX_TOKENS", 2048)))
        self.relevance_max_tokens_retry = max(
            self.relevance_max_tokens,
            int(self.config_manager.get("OPENAI_RELEVANCE_MAX_TOKENS_RETRY", 4096)),
        )
        self.relevance_content_max_chars = max(
            500, int(self.config_manager.get("OPENAI_RELEVANCE_CONTENT_MAX_CHARS", 12000))
        )
        self.relevance_metadata_max_chars = max(
            0, int(self.config_manager.get("OPENAI_RELEVANCE_METADATA_MAX_CHARS", 800))
        )
        
        # Store context message from config first, with optional explicit override.
        self.context_message = context_message or self.config_manager.get_context_message()
        # Cancellation flag controlled by pipeline/GUI
        self.cancelled = False

    def _render_user_prompt(self, article_text: str) -> str:
        """Build the user prompt from configured context plus article payload."""
        context_content = (
            self.context_message.get("content", "")
            if isinstance(self.context_message, dict)
            else str(self.context_message or "")
        ).strip()
        return (
            f"{context_content}\n\n"
            f"Article:\n"
            f"{article_text}"
        )

    def cancel(self) -> None:
        """Signal the processor to stop processing new articles."""
        self.cancelled = True

    def _build_error_result(self, article_id: Any, error: Exception) -> ProcessingResult:
        """Return a uniform processing error payload while tracking metrics."""
        logger.exception("Error processing article ID %s", article_id if article_id is not None else "")
        try:
            self.error_count += 1
        except AttributeError:
            self.error_count = 1
        return ProcessingResult(article=None, status="error", error=str(error))

    @staticmethod
    def _cap_llm_text(value: Any, max_len: int) -> str:
        if max_len <= 0:
            return ""
        text = str(value or "").strip()
        if len(text) <= max_len:
            return text
        suffix = "\n[...truncated for LLM...]"
        keep = max_len - len(suffix)
        if keep <= 0:
            return text[:max_len]
        return text[:keep] + suffix

    def _format_article_for_llm(self, article: Dict[str, Any], title: str, content: str) -> str:
        content_cap = max(500, int(getattr(self, "relevance_content_max_chars", 12000)))
        meta_cap = int(getattr(self, "relevance_metadata_max_chars", 800))
        meta_cap = meta_cap if meta_cap > 0 else 2000
        return (
            f"Raw Article ID: {article.get('id', '')}\n"
            f"Title: {self._cap_llm_text(title, meta_cap)}\n"
            f"Content: {self._cap_llm_text(content, content_cap)}\n"
            f"URL: {self._cap_llm_text(article.get('url', ''), meta_cap)}\n"
            f"Event URI: {self._cap_llm_text(article.get('event_uri', ''), meta_cap)}\n"
            f"Event Type URI: {self._cap_llm_text(article.get('event_type_uri', ''), meta_cap)}\n"
            f"Incident Sentence: {self._cap_llm_text(article.get('incident_sentence', ''), meta_cap)}\n"
            f"Location Metadata: {self._cap_llm_text(article.get('location', ''), meta_cap)}\n"
            f"Categories Metadata: {self._cap_llm_text(article.get('categories', ''), meta_cap)}\n"
            f"Concepts Metadata: {self._cap_llm_text(article.get('concepts', ''), meta_cap)}\n"
            f"Extracted Dates Metadata: {self._cap_llm_text(article.get('extracted_dates', ''), meta_cap)}"
        )

    def _openai_parse_relevance(self, user_content: str) -> RatedArticle:
        """Call OpenAI structured parse with length-limit retry."""
        primary = max(256, int(getattr(self, "relevance_max_tokens", 2048)))
        retry_cap = max(primary, int(getattr(self, "relevance_max_tokens_retry", 4096)))
        last_error: Optional[Exception] = None
        for max_out in (primary, retry_cap):
            try:
                response = self.client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": user_content}],
                    max_tokens=max_out,
                    temperature=0,
                    response_format=RatedArticle,
                )
                if not response.choices or not response.choices[0].message:
                    raise RuntimeError("empty response from OpenAI")
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise RuntimeError("empty parsed response from OpenAI")
                return parsed
            except LengthFinishReasonError as exc:
                last_error = exc
                logger.warning(
                    "OpenAI relevance parse truncated (max_tokens=%s); retrying if possible",
                    max_out,
                )
                if max_out >= retry_cap:
                    break
                continue
        if last_error:
            raise last_error
        raise RuntimeError("OpenAI relevance parse failed without specific error")

    def _record_processing_outcome(
        self,
        raw_article_id: Optional[int],
        relevance_score: float,
        status: str,
        explanation: str = "",
        event: str = "",
        who_entities: str = "",
        where_location: str = "",
        impact: str = "",
        urgency: str = "",
        why_it_matters: str = "",
        incident_sentence: str = "",
        event_type_uri: str = "",
    ) -> None:
        """Persist processing result when a raw article id is available."""
        if raw_article_id is None:
            return

        self.article_manager.record_processing_result(
            raw_article_id=raw_article_id,
            relevance_score=relevance_score,
            status=status,
            explanation=explanation,
            event=event,
            who_entities=who_entities,
            where_location=where_location,
            impact=impact,
            urgency=urgency,
            why_it_matters=why_it_matters,
            incident_sentence=incident_sentence,
            event_type_uri=event_type_uri,
        )

    def _store_relevant_article(
        self,
        article: Dict[str, Any],
        raw_article_id: Optional[int],
        source: str,
        relevance_score: float,
        include_extended_fields: bool = False,
        explanation: str = "",
        event: str = "",
        who_entities: str = "",
        where_location: str = "",
        impact: str = "",
        urgency: str = "",
        why_it_matters: str = "",
    ) -> ProcessingResult:
        """Persist relevant article details and return a relevant result."""
        self.relevant += 1
        self.max_relevance_score = max(self.max_relevance_score, relevance_score)
        insert_kwargs = {
            "raw_article_id": raw_article_id,
            "title": article.get("title", ""),
            "content": article.get("content", ""),
            "source": source,
            "url": article.get("url", ""),
            "url_to_image": article.get("url_to_image", ""),
            "published_at": article.get("published_at", ""),
            "relevance_score": relevance_score,
        }
        api_fields = getattr(self.article_manager, "api_fields_from_article", None)
        if callable(api_fields):
            insert_kwargs.update(api_fields(article))
        if include_extended_fields:
            insert_kwargs.update(
                {
                    "explanation": explanation,
                    "event": event,
                    "who_entities": who_entities,
                    "where_location": where_location,
                    "impact": impact,
                    "urgency": urgency,
                    "why_it_matters": why_it_matters,
                    "incident_sentence": article.get("incident_sentence", ""),
                    "event_type_uri": article.get("event_type_uri", ""),
                }
            )

        self.article_manager.insert_relevant_article(
            **insert_kwargs
        )
        return ProcessingResult(article=article, status="relevant")

    def get_context_data(self, article: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve relevant context data for the article.
        
        This is a placeholder for a future RAG (Retrieval-Augmented Generation) implementation.
        Currently returns basic article information formatted for the OpenAI API.
        
        Args:
            article: Dictionary containing article data
            
        Returns:
            List of context data dictionaries formatted for OpenAI API
        """
        # Basic implementation - in a real RAG system, this would retrieve similar articles
        # or domain-specific knowledge to enhance the context
        return [
            {
                "type": "text",
                "text": "Context: This analysis focuses on pharmaceutical security and supply chain integrity."
            },
            {
                "type": "text",
                "text": f"Article Title: {article.get('title', '')}"
            },
            {
                "type": "text",
                "text": f"Article Content: {article.get('content', '')}"
            }
        ]

    async def process_article(
        self,
        article: Dict[str, Any],
        remaining: int,
        attempt: int = 1,
        max_retries: int = 3,
    ) -> ProcessingResult:
        """Process a single article and return a structured result."""
        if not isinstance(article, dict):
            self.error_count += 1
            logger.error("process_article expected dict article, got %s", type(article).__name__)
            return ProcessingResult(article=None, status="error", error="invalid article payload")
        if max_retries < 1:
            self.error_count += 1
            logger.error("process_article called with invalid max_retries=%s", max_retries)
            return ProcessingResult(article=None, status="error", error="invalid retry configuration")
        if not self.client:
            self.error_count += 1
            logger.error("OpenAI client is not initialized")
            return ProcessingResult(article=None, status="error", error="client not initialized")

        try:
            if getattr(self, "cancelled", False):
                logger.info("Article processing cancelled before starting item")
                self.error_count += 1
                return ProcessingResult(article=None, status="error", error="cancelled")
            article_id = article.get('id')
            source = extract_source_name(article.get('source', 'Unknown Source'), default='Unknown Source')
            title = article.get("title", "")
            content = article.get("content", "") or article.get("snippet", "")
            combined_text = f"{title} {content}"
            article["incident_level"] = is_incident_article(combined_text)[0]
                
            logger.info(f"Processing article - ID: {article_id}, URL: {article.get('url', 'No URL')}")
            
            # Get existing processing result if available
            if article_id:
                existing = self.db_manager.execute_query(
                    """
                    SELECT relevance_score, explanation, event, who_entities, where_location,
                           impact, urgency, why_it_matters, incident_sentence, event_type_uri
                    FROM relevant_articles
                    WHERE raw_article_id = ?
                    """,
                    (article_id,)
                )
                if existing:
                    logger.info(f"Using existing relevance score for article {article_id}")
                    existing_row = existing[0]
                    article['relevance_score'] = existing_row['relevance_score']
                    for field in (
                        'explanation',
                        'event',
                        'who_entities',
                        'where_location',
                        'impact',
                        'urgency',
                        'why_it_matters',
                        'incident_sentence',
                        'event_type_uri',
                    ):
                        article[field] = existing_row.get(field, '')
                    return ProcessingResult(article=article, status="relevant")
            
            # Continue with regular processing
            logger.info(f"RELEVANCE_THRESHOLD: {self.RELEVANCE_THRESHOLD}")

            # Deterministic pre-filter to avoid unnecessary LLM calls.
            skip_llm, default_score = should_skip_llm(
                title,
                content,
                query_language=str(article.get("query_language", "") or ""),
            )
            if not getattr(self, "enable_llm_guardrail", True):
                skip_llm = False
            if skip_llm:
                relevance_score = float(default_score if default_score is not None else 0.0)
                status = "relevant" if relevance_score >= self.RELEVANCE_THRESHOLD else "irrelevant"
                article["relevance_score"] = relevance_score
                article["processing_status"] = status
                article["incident_level"] = False
                article["explanation"] = "Pre-filtered: missing enforcement or pharma keywords"
                article["why_it_matters"] = ""

                self._record_processing_outcome(
                    raw_article_id=article_id,
                    relevance_score=relevance_score,
                    status=status,
                    explanation=article["explanation"],
                )

                if status == "relevant":
                    return self._store_relevant_article(
                        article=article,
                        raw_article_id=article_id,
                        source=source,
                        relevance_score=relevance_score,
                    )

                self.irrelevant += 1
                return ProcessingResult(article=None, status="irrelevant")

            await self.rate_limiter.wait_if_needed_async()

            try:
                async with self.semaphore:
                    article["incident_level"] = True
                    article_text = self._format_article_for_llm(article, title, content)
                    user_prompt = self._render_user_prompt(article_text)
                    try:
                        parsed_response = self._openai_parse_relevance(user_prompt)
                    except Exception as exc:
                        return self._build_error_result(article.get("id", ""), exc)

                    relevance_score = parsed_response.relevance_score
                    explanation = getattr(parsed_response, "explanation", "")
                    event = getattr(parsed_response, "event", "")
                    who_entities = getattr(parsed_response, "who_entities", "")
                    where_location = getattr(parsed_response, "where_location", "")
                    impact = getattr(parsed_response, "impact", "")
                    urgency = getattr(parsed_response, "urgency", "")
                    why_it_matters = getattr(parsed_response, "why_it_matters", "")
                    raw_article_id = article.get('id')
                    url = article.get('url')
                    status = "relevant" if relevance_score >= self.RELEVANCE_THRESHOLD else "irrelevant"

                    logger.info(f"Processing article - ID: {raw_article_id}, URL: {url}, Score: {relevance_score}")
                    logger.info(f"RELEVANCE_THRESHOLD: {self.RELEVANCE_THRESHOLD}")

                    # Persist the score on the article for downstream consumers
                    article["relevance_score"] = relevance_score
                    article["explanation"] = explanation
                    article["event"] = event
                    article["who_entities"] = who_entities
                    article["where_location"] = where_location
                    article["impact"] = impact
                    article["urgency"] = urgency
                    article["why_it_matters"] = why_it_matters
                    article["processing_status"] = status

                    self._record_processing_outcome(
                        raw_article_id=raw_article_id,
                        relevance_score=relevance_score,
                        status=status,
                        explanation=explanation,
                        event=event,
                        who_entities=who_entities,
                        where_location=where_location,
                        impact=impact,
                        urgency=urgency,
                        why_it_matters=why_it_matters,
                        incident_sentence=article.get("incident_sentence", ""),
                        event_type_uri=article.get("event_type_uri", ""),
                    )

                    # Process and store relevant articles
                    if status == "relevant":
                        logger.info(f"Article with ID '{raw_article_id}' is relevant (score: {relevance_score})")
                        return self._store_relevant_article(
                            article=article,
                            raw_article_id=raw_article_id,
                            source=source,
                            relevance_score=relevance_score,
                            include_extended_fields=True,
                            explanation=explanation,
                            event=event,
                            who_entities=who_entities,
                            where_location=where_location,
                            impact=impact,
                            urgency=urgency,
                            why_it_matters=why_it_matters,
                        )
                    else:
                        self.irrelevant += 1
                        logger.info(f"❌ Article with ID '{raw_article_id}' is not relevant (score: {relevance_score})")
                        return ProcessingResult(article=None, status="irrelevant")

            except RateLimitError as e:
                logger.warning(f"Rate limit exceeded (attempt {attempt}/{max_retries}): {e}")
                if attempt >= max_retries:
                    self.error_count += 1
                    return ProcessingResult(
                        article=None,
                        status="error",
                        error="rate limit exceeded after retries",
                    )
                backoff_seconds = min(60, 2 ** attempt)
                await asyncio.sleep(backoff_seconds)
                return await self.process_article(
                    article,
                    remaining,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                )
            except Exception as e:
                return self._build_error_result(article.get("id", ""), e)

        except Exception as e:
            return self._build_error_result(article.get("id", ""), e)

    async def process_articles(self, articles: List[Dict[str, Any]]) -> List[ProcessingResult]:
        """Process articles in optimized batches and return structured results."""
        if articles is None:
            logger.warning("process_articles received None, treating as empty list")
            return []
        if not isinstance(articles, list):
            logger.error("process_articles expected list, got %s", type(articles).__name__)
            return []
        if not articles:
            return []

        total_to_process = len(articles)
        remaining = total_to_process
        results: List[ProcessingResult] = []

        batch_size = max(1, int(getattr(self, "batch_size", 10)))
        for i in range(0, total_to_process, batch_size):
            batch = articles[i : i + batch_size]

            for article in batch:
                if getattr(self, "cancelled", False):
                    logger.info("Batch processing cancelled by user")
                    break
                try:
                    result = await self.process_article(article, remaining)
                except Exception as exc:
                    logger.exception(
                        "Unexpected error processing article id=%s",
                        article.get("id") if isinstance(article, dict) else None,
                    )
                    try:
                        self.error_count += 1
                    except AttributeError:
                        self.error_count = 1
                    result = ProcessingResult(
                        article=None,
                        status="error",
                        error=str(exc),
                    )
                results.append(result)
                remaining -= 1

                processed_so_far = total_to_process - remaining
                if hasattr(self, "progress_callback"):
                    self.progress_callback(processed_so_far, total_to_process)

            if getattr(self, "cancelled", False):
                break

        return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)  # Fix logging setup
    try:
        db_manager = DatabaseManager()
        processor = ArticleProcessor(db_manager=db_manager)
        article_manager = ArticleManager(db_manager)
        articles = article_manager.get_articles()
        
        # Run async processing
        results = asyncio.run(processor.process_articles(articles))

        if results:
            relevant_count = len([r for r in results if r.status == "relevant"])
            error_count = len([r for r in results if r.status == "error"])
            from src.analysis_utils import calculate_relevance_stats, print_analysis_results
            
            analysis_results = calculate_relevance_stats(
                processor.relevant,
                processor.irrelevant,
                processor.max_relevance_score,
            )
            logger.info(f"Processing completed. Processed {len(results)} articles. Relevant: {relevant_count}, Errors: {error_count}")
            print_analysis_results(analysis_results)
        else:
            logger.error("Processing failed")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        db_manager.close()

