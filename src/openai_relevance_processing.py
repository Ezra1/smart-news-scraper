import os
import sys
import time
import asyncio
import logging  # Add this import for logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from openai import OpenAI, RateLimitError
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
        self.semaphore = asyncio.Semaphore(5)  # Limit concurrent requests
        
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
        self.enable_llm_guardrail = bool(self.config_manager.get("PRELLM_ENABLE_LLM_GUARDRAIL", True))
        
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
        self.error_count += 1
        return ProcessingResult(article=None, status="error", error=str(error))

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
            if self.cancelled:
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
            skip_llm, default_score = should_skip_llm(title, content)
            if not self.enable_llm_guardrail:
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
                    article_text = (
                        f"Raw Article ID: {article.get('id', '')}\n"
                        f"Title: {title}\n"
                        f"Content: {content}\n"
                        f"URL: {article.get('url', '')}\n"
                        f"Event URI: {article.get('event_uri', '')}\n"
                        f"Event Type URI: {article.get('event_type_uri', '')}\n"
                        f"Incident Sentence: {article.get('incident_sentence', '')}\n"
                        f"Location Metadata: {article.get('location', '')}\n"
                        f"Categories Metadata: {article.get('categories', '')}\n"
                        f"Concepts Metadata: {article.get('concepts', '')}\n"
                        f"Extracted Dates Metadata: {article.get('extracted_dates', '')}"
                    )
                    
                    # Process article through OpenAI API
                    response = self.client.beta.chat.completions.parse(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "user",
                                "content": self._render_user_prompt(article_text),
                            }
                        ],
                        max_tokens=250,
                        temperature=0,
                        response_format=RatedArticle
                    )

                    if not response.choices or not response.choices[0].message:
                        logger.error(f"No response received for article ID: {article.get('id', '')}")
                        self.error_count += 1
                        return ProcessingResult(
                            article=None,
                            status="error",
                            error="empty response from OpenAI",
                        )

                    # Extract relevance score from response
                    parsed_response = response.choices[0].message.parsed
                    if parsed_response is None:
                        logger.error("Parsed OpenAI response is empty for article ID: %s", article.get("id", ""))
                        self.error_count += 1
                        return ProcessingResult(article=None, status="error", error="empty parsed response")
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

        try:
            total_to_process = len(articles)
            remaining = total_to_process
            results: List[ProcessingResult] = []
            
            for i in range(0, total_to_process, self.batch_size):
                batch = articles[i:i + self.batch_size]
                
                # Process articles one by one and emit progress after each item
                for article in batch:
                    if self.cancelled:
                        logger.info("Batch processing cancelled by user")
                        break
                    result = await self.process_article(article, remaining)
                    results.append(result)
                    remaining -= 1

                    processed_so_far = total_to_process - remaining
                    if hasattr(self, 'progress_callback'):
                        self.progress_callback(processed_so_far, total_to_process)
                
                if self.cancelled:
                    break
            
            return results
            
        except Exception as e:
            logger.exception("Error processing articles")
            return []

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

