import aiohttp
import asyncio
import json
import re
from time import perf_counter
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from src.database_manager import ArticleManager, DatabaseManager
from src.logger_config import setup_logging
from src.incident_filter import is_incident_article
from src.url_content_extractor import fetch_readable_text

logger = setup_logging(__name__)

from src.config import ConfigManager
from src.utils.article_normalization import (
    extract_source_name,
    normalize_domain,
    parse_csv_domain_list,
)
from src.utils.rate_limiter import RateLimiter

CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
MAX_ARTICLE_PAGES = 10
RATE_LIMIT_WINDOW_SECONDS = 60
HTTP_UNAUTHORIZED = 401
HTTP_PAYMENT_REQUIRED = 402
HTTP_FORBIDDEN = 403
HTTP_BAD_REQUEST = 400
HTTP_TOO_MANY_REQUESTS = 429
THENEWSAPI_HOST = "thenewsapi.com"
DEFAULT_THENEWSAPI_BASE_URL = "https://api.thenewsapi.com/v1/news"


class NewsArticleScraper:
    """Fetch and enrich articles using TheNewsAPI."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db_manager: Optional[DatabaseManager] = None,
        db_path: Optional[str] = None,
    ):
        self.config = config_manager
        self.api_key = self.config.get("NEWS_API_KEY")
        self.api_base_url = self._resolve_news_api_base_url(
            configured_url=self.config.get("NEWS_API_BASE_URL", DEFAULT_THENEWSAPI_BASE_URL),
            default_url=DEFAULT_THENEWSAPI_BASE_URL,
            setting_name="NEWS_API_BASE_URL",
        )
        self.api_url = f"{self.api_base_url}/all"
        self.rate_limited = False
        self.partial_results = []

        self.db_manager = db_manager or DatabaseManager(db_path or "news_articles.db")
        self.article_manager = ArticleManager(self.db_manager)

        requests_per_second = config_manager.get("NEWS_API_REQUESTS_PER_SECOND", 1)
        self.rate_limiter = RateLimiter(requests_per_second=requests_per_second)
        self.max_requests_per_second = float(config_manager.get("NEWS_API_MAX_REQUESTS_PER_SECOND", 10) or 10)
        self.min_requests_per_second = float(config_manager.get("NEWS_API_MIN_REQUESTS_PER_SECOND", 0.2) or 0.2)
        self.rate_limit_headroom = float(config_manager.get("NEWS_API_RATE_LIMIT_HEADROOM", 0.90) or 0.90)
        self._resume_requests_at = 0.0
        self.articles_count = int(self.config.get("NEWS_API_PAGE_LIMIT", 50))
        self.max_pages_per_query = int(self.config.get("FETCH_MAX_PAGES_PER_QUERY", MAX_ARTICLE_PAGES))
        self.min_body_length = int(self.config.get("NEWS_API_MIN_BODY_LENGTH", 600))
        self.enable_url_fallback = bool(self.config.get("NEWS_API_ENABLE_URL_FALLBACK", True))
        self.url_fallback_timeout_seconds = int(self.config.get("NEWS_API_URL_FALLBACK_TIMEOUT_SECONDS", 15))
        self.url_fallback_max_concurrency = int(self.config.get("NEWS_API_URL_FALLBACK_MAX_CONCURRENCY", 8))
        self.url_fallback_semaphore = (
            asyncio.Semaphore(self.url_fallback_max_concurrency)
            if self.url_fallback_max_concurrency > 0
            else None
        )
        self.raw_insert_batch_size = int(self.config.get("RAW_ARTICLE_INSERT_BATCH_SIZE", 100))
        self.language = str(self.config.get("NEWS_API_LANGUAGE", "en") or "").strip()
        self.source_allowlist = self._parse_csv_list(self.config.get("NEWS_SOURCE_ALLOWLIST", ""))
        self.source_blocklist = self._parse_csv_list(self.config.get("NEWS_SOURCE_BLOCKLIST", ""))
        self._run_metrics: Dict[str, float] = {}
        logger.info(
            "Initialized TheNewsAPI scraper | api_url=%s lang=%s limit=%s",
            self.api_url,
            self.language or "<any>",
            self.articles_count,
        )

    @staticmethod
    def _resolve_news_api_base_url(configured_url: Any, default_url: str, setting_name: str) -> str:
        """Ensure configured base URL points to TheNewsAPI endpoints."""
        candidate = str(configured_url or "").strip()
        if not candidate:
            return default_url

        candidate = candidate.rstrip("/")
        normalized = candidate.lower()
        if THENEWSAPI_HOST in normalized:
            return candidate

        logger.warning(
            "%s is set to non-TheNewsAPI URL '%s'; falling back to '%s'",
            setting_name,
            candidate,
            default_url,
        )
        return default_url

    @staticmethod
    def _extract_api_error_message(data: Any) -> str:
        """Extract common API error payload shapes into a readable message."""
        if not isinstance(data, dict):
            return ""

        error_value = data.get("error")
        if isinstance(error_value, str) and error_value.strip():
            return error_value.strip()
        if isinstance(error_value, dict):
            message = error_value.get("message") or error_value.get("description")
            if isinstance(message, str) and message.strip():
                return message.strip()

        errors_value = data.get("errors")
        if isinstance(errors_value, list):
            messages = [str(item).strip() for item in errors_value if str(item).strip()]
            if messages:
                return "; ".join(messages)
        if isinstance(errors_value, dict):
            messages = [str(v).strip() for v in errors_value.values() if str(v).strip()]
            if messages:
                return "; ".join(messages)

        message_value = data.get("message")
        if isinstance(message_value, str) and message_value.strip():
            return message_value.strip()

        return ""

    async def fetch_articles(
        self,
        search_terms: List[Any],
        search_term_map: Dict[str, int],
        date_params: Optional[Dict[str, str]] = None,
    ) -> List[dict]:
        """Fetch and process articles for search terms."""
        if not isinstance(search_terms, list):
            logger.error("fetch_articles expected list search_terms, got %s", type(search_terms).__name__)
            return []
        if not search_terms:
            return []
        if not isinstance(search_term_map, dict):
            logger.error("fetch_articles expected dict search_term_map, got %s", type(search_term_map).__name__)
            return []

        all_articles = []
        self.rate_limited = False
        self._run_metrics = {
            "raw_fetched_count": 0,
            "enriched_count": 0,
            "persisted_count": 0,
            "fallback_attempt_count": 0,
            "fallback_seconds": 0.0,
            "db_persist_seconds": 0.0,
        }

        for term_entry in search_terms:
            query_spec = self._normalize_query_spec(term_entry)
            if not query_spec:
                logger.warning("Skipping invalid search term: %r", term_entry)
                continue
            term = query_spec["term"]
            root_term = query_spec["root_term"]
            try:
                raw_articles = await self._fetch_for_term(term, date_params, query_spec=query_spec)
                if self.rate_limited:
                    break
                self._run_metrics["raw_fetched_count"] += len(raw_articles)

                mention_map: Dict[str, Dict[str, str]] = {}
                enriched_candidates: List[Dict[str, Any]] = []
                for raw in raw_articles:
                    article_data = await self._enrich_article_data(
                        raw_article=raw,
                        search_term_id=search_term_map.get(root_term),
                        mention_map=mention_map,
                        preserve_existing_mention_values=True,
                        query_term=term,
                        query_language=query_spec.get("language", ""),
                        root_term=root_term,
                    )
                    if not article_data:
                        continue
                    self._run_metrics["enriched_count"] += 1
                    title = article_data.get("title", "")
                    content = article_data.get("content", "")
                    article_data["incident_level"] = is_incident_article(f"{title} {content}")[0]
                    enriched_candidates.append(article_data)

                persisted = self._persist_articles_batch(enriched_candidates)
                all_articles.extend(persisted)

                logger.info(
                    "Processed %s TheNewsAPI articles for term='%s' (root='%s', lang='%s')",
                    len(raw_articles),
                    term,
                    root_term,
                    query_spec.get("language", ""),
                )
            except Exception as e:
                logger.error("Error processing articles for term '%s': %s", term, e)
        self._log_ingestion_run_summary()
        return all_articles

    def _normalize_query_spec(self, term_entry: Any) -> Optional[Dict[str, Any]]:
        if isinstance(term_entry, str):
            term = term_entry.strip()
            if not term:
                return None
            return {
                "term": term,
                "root_term": term,
                "language": self.language,
            }
        if isinstance(term_entry, dict):
            term = str(term_entry.get("term", "")).strip()
            if not term:
                return None
            root_term = str(term_entry.get("root_term", term)).strip() or term
            language = str(term_entry.get("language", self.language) or "").strip()
            return {
                "term": term,
                "root_term": root_term,
                "language": language,
            }
        return None

    async def _fetch_for_term(
        self,
        term: str,
        date_params: Optional[Dict[str, str]] = None,
        query_spec: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        if not isinstance(term, str) or not term.strip():
            logger.warning("Skipping fetch for empty/invalid term: %r", term)
            return []

        logger.info("Fetching articles for term: %s", term)
        try:
            date_filters = self._resolve_date_filters(date_params)
            all_articles = await self._fetch_articles_pages(term, date_filters, query_spec=query_spec)

            # If user-provided date filters are too restrictive for the account
            # window, retry with the default recent window before giving up.
            if not all_articles and date_filters:
                fallback_filters = self._resolve_date_filters(None)
                logger.warning(
                    "No TheNewsAPI results for term '%s' with date filters %s. "
                    "Retrying with fallback window %s.",
                    term,
                    date_filters,
                    fallback_filters,
                )
                all_articles = await self._fetch_articles_pages(term, fallback_filters, query_spec=query_spec)
                for article in all_articles:
                    if isinstance(article, dict):
                        article["_retrieved_via_fallback_window"] = True

            logger.info("Found %s articles for term: %s", len(all_articles), term)
            return all_articles
        except Exception as e:
            logger.error("Error fetching articles for term '%s': %s", term, e)
            return []

    async def _fetch_articles_pages(
        self,
        term: str,
        date_filters: Dict[str, str],
        query_spec: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        if not isinstance(term, str) or not term.strip():
            logger.warning("_fetch_articles_pages called with empty/invalid term: %r", term)
            return []
        if not isinstance(date_filters, dict):
            logger.error("_fetch_articles_pages expected date_filters dict, got %s", type(date_filters).__name__)
            return []

        all_articles: List[Dict] = []
        max_pages = max(1, int(self.max_pages_per_query or MAX_ARTICLE_PAGES))
        for page in range(1, max_pages + 1):
            await self._wait_for_rate_limit()
            payload = self._build_articles_payload(term, page, date_filters, query_spec=query_spec)
            page_articles = await self._make_api_request(payload)
            if not page_articles:
                break
            all_articles.extend(page_articles)
            if len(page_articles) < self.articles_count:
                break
        return all_articles

    def _build_articles_payload(
        self,
        term: str,
        page: int,
        date_filters: Dict[str, str],
        query_spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "api_token": self.api_key,
            "search": self._build_search_query(term),
            "page": page,
            "limit": self.articles_count,
        }
        language = self.language
        if isinstance(query_spec, dict):
            language = str(query_spec.get("language", language) or "").strip()
        if language:
            payload["language"] = language
        payload.update(date_filters)
        return payload

    async def _make_api_request(self, payload: dict) -> List[dict]:
        """Make request to TheNewsAPI /all endpoint."""
        if not isinstance(payload, dict):
            logger.error("_make_api_request expected dict payload, got %s", type(payload).__name__)
            return []
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            logger.error("TheNewsAPI token is missing; cannot fetch articles")
            return []
        if not self.api_url:
            logger.error("TheNewsAPI URL is not configured")
            return []

        try:
            async with aiohttp.ClientSession(timeout=CLIENT_TIMEOUT, trust_env=True) as session:
                async with session.get(self.api_url, params=payload) as response:
                    self._adapt_rate_limit_from_headers(response.headers)
                    if response.status == 200:
                        data = await response.json()
                        api_error = self._extract_api_error_message(data)
                        if api_error:
                            logger.error(
                                "TheNewsAPI returned API error with HTTP 200: %s | params=%s",
                                api_error,
                                payload,
                            )
                            return []
                        return self._extract_articles_from_response(data)
                    if response.status in (HTTP_PAYMENT_REQUIRED, HTTP_TOO_MANY_REQUESTS):
                        self._set_resume_from_headers(response.headers)
                        logger.warning("Rate limit/plan limit exceeded for TheNewsAPI")
                        self.rate_limited = True
                        return []
                    if response.status == HTTP_UNAUTHORIZED:
                        logger.error("Invalid TheNewsAPI token")
                        return []
                    if response.status == HTTP_FORBIDDEN:
                        logger.error("TheNewsAPI endpoint access restricted (403)")
                        return []
                    if response.status == HTTP_BAD_REQUEST:
                        response_text = await response.text()
                        logger.error("Malformed TheNewsAPI parameters: %s", response_text)
                        return []
                    response_text = await response.text()
                    logger.error(
                        "TheNewsAPI request failed with status %s | params=%s | response=%s",
                        response.status,
                        payload,
                        response_text,
                    )
                    return []
        except asyncio.TimeoutError:
            logger.error("TheNewsAPI request timed out")
            return []
        except Exception as e:
            logger.error("TheNewsAPI request error: %s", e)
            return []

    def _extract_results_list(self, data: Dict[str, Any], nested_key: str) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            results = nested.get("results", [])
            return results if isinstance(results, list) else []
        if isinstance(nested, list):
            return nested
        if isinstance(data.get("results"), list):
            return data["results"]
        return []

    def _extract_articles_from_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        articles = data.get("data", [])
        return articles if isinstance(articles, list) else []

    def _extract_mentions_from_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._extract_results_list(data, "mentions")

    def _extract_mention_article_url(self, mention: Dict[str, Any]) -> str:
        article = mention.get("article", {}) if isinstance(mention, dict) else {}
        if isinstance(article, dict):
            return article.get("url") or article.get("uri") or ""
        return ""

    def _extract_mention_sentence(self, mention: Dict[str, Any]) -> str:
        if not isinstance(mention, dict):
            return ""
        for key in ("sentence", "mention", "text"):
            value = mention.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _extract_mention_event_type(self, mention: Dict[str, Any]) -> str:
        if not isinstance(mention, dict):
            return ""
        event_type = mention.get("eventType")
        if isinstance(event_type, dict):
            return event_type.get("uri", "")
        if isinstance(event_type, str):
            return event_type
        return mention.get("eventTypeUri", "")

    async def _maybe_apply_url_fallback(self, article_data: Dict[str, Any]) -> None:
        if not isinstance(article_data, dict):
            logger.error("_maybe_apply_url_fallback expected dict article_data, got %s", type(article_data).__name__)
            return

        content = str(article_data.get("content", "") or "")
        if not self.enable_url_fallback or len(content) >= self.min_body_length:
            article_data["body_source"] = "thenewsapi"
            return

        self._run_metrics["fallback_attempt_count"] = self._run_metrics.get("fallback_attempt_count", 0) + 1
        fallback_start = perf_counter()
        if self.url_fallback_semaphore is not None:
            async with self.url_fallback_semaphore:
                fallback_text, status = await fetch_readable_text(
                    article_data.get("url", ""),
                    timeout_seconds=self.url_fallback_timeout_seconds,
                    min_length=self.min_body_length,
                )
        else:
            fallback_text, status = await fetch_readable_text(
                article_data.get("url", ""),
                timeout_seconds=self.url_fallback_timeout_seconds,
                min_length=self.min_body_length,
            )
        self._run_metrics["fallback_seconds"] = self._run_metrics.get("fallback_seconds", 0.0) + (
            perf_counter() - fallback_start
        )
        article_data["url_fallback_status"] = status
        if fallback_text and len(fallback_text) > len(content):
            article_data["content"] = fallback_text
            article_data["full_text"] = fallback_text
            article_data["body_source"] = "url_fallback"
        else:
            article_data["body_source"] = "thenewsapi"

    async def _enrich_article_data(
        self,
        raw_article: Dict[str, Any],
        search_term_id: Optional[int],
        mention_map: Dict[str, Dict[str, str]],
        preserve_existing_mention_values: bool,
        query_term: str = "",
        query_language: str = "",
        root_term: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Normalize and enrich a raw article payload for downstream processing."""
        if not isinstance(raw_article, dict):
            logger.warning("Skipping invalid raw article payload: %r", raw_article)
            return None

        article_data = self._normalize_article(raw_article)
        if not self._is_source_allowed(article_data):
            logger.info(
                "Skipping article due to source filtering | url=%s",
                article_data.get("url", ""),
            )
            return None

        article_data["search_term_id"] = search_term_id
        article_data["query_term"] = str(query_term or "").strip()
        article_data["query_language"] = str(query_language or "").strip().lower()
        article_data["root_term"] = str(root_term or "").strip()
        article_url = article_data.get("url", "")
        mention_meta = mention_map.get(article_url, {}) if isinstance(mention_map, dict) else {}
        event_type_uri = mention_meta.get("event_type_uri", "")
        incident_sentence = mention_meta.get("incident_sentence", "")

        if preserve_existing_mention_values:
            article_data["event_type_uri"] = article_data.get("event_type_uri") or event_type_uri
            article_data["incident_sentence"] = article_data.get("incident_sentence") or incident_sentence
        else:
            article_data["event_type_uri"] = event_type_uri
            article_data["incident_sentence"] = incident_sentence

        article_data["retrieval_fallback_window"] = bool(
            raw_article.get("_retrieved_via_fallback_window", False)
        )
        await self._maybe_apply_url_fallback(article_data)
        return article_data

    def _persist_article(self, article_data: Dict[str, Any]) -> bool:
        """Persist normalized article data and annotate it with DB id."""
        if not isinstance(article_data, dict):
            logger.error("_persist_article expected dict article_data, got %s", type(article_data).__name__)
            return False

        try:
            persist_start = perf_counter()
            article_id = self.article_manager.insert_article(article_data)
            self._run_metrics["db_persist_seconds"] = self._run_metrics.get("db_persist_seconds", 0.0) + (
                perf_counter() - persist_start
            )
            if not article_id:
                return False
            article_data["id"] = article_id
            self._run_metrics["persisted_count"] = self._run_metrics.get("persisted_count", 0) + 1
            return True
        except Exception as e:
            logger.error("Failed to persist article '%s': %s", article_data.get("url", ""), e)
            return False

    def _persist_articles_batch(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Persist articles in conservative batches and return successful rows."""
        if not isinstance(articles, list):
            logger.error("_persist_articles_batch expected list, got %s", type(articles).__name__)
            return []
        if not articles:
            return []

        batch_size = max(1, int(self.raw_insert_batch_size or 100))
        persisted: List[Dict[str, Any]] = []
        for idx in range(0, len(articles), batch_size):
            batch = articles[idx: idx + batch_size]
            persist_start = perf_counter()
            inserted_ids = self.article_manager.insert_articles_batch(batch)
            self._run_metrics["db_persist_seconds"] = self._run_metrics.get("db_persist_seconds", 0.0) + (
                perf_counter() - persist_start
            )
            for article, article_id in zip(batch, inserted_ids):
                if not article_id:
                    continue
                article["id"] = article_id
                self._run_metrics["persisted_count"] = self._run_metrics.get("persisted_count", 0) + 1
                persisted.append(article)
        return persisted

    def _log_ingestion_run_summary(self) -> None:
        """Emit one summary line for ingestion performance observability."""
        if not isinstance(self._run_metrics, dict):
            return
        logger.info(
            (
                "Ingestion summary | raw_fetched=%s enriched=%s persisted=%s "
                "fallback_attempts=%s fallback_seconds=%.2f db_persist_seconds=%.2f"
            ),
            int(self._run_metrics.get("raw_fetched_count", 0)),
            int(self._run_metrics.get("enriched_count", 0)),
            int(self._run_metrics.get("persisted_count", 0)),
            int(self._run_metrics.get("fallback_attempt_count", 0)),
            float(self._run_metrics.get("fallback_seconds", 0.0)),
            float(self._run_metrics.get("db_persist_seconds", 0.0)),
        )

    def _normalize_article(self, article: Dict[str, Any]) -> Dict[str, Any]:
        title = article.get("title") or article.get("articleTitle") or ""
        body = article.get("description") or article.get("content") or article.get("body") or ""
        snippet = article.get("snippet") or ""
        if not body and snippet:
            body = snippet
        if not body:
            body = title

        source = article.get("source") or {}
        source_name = extract_source_name(source)

        location = article.get("location") or article.get("articleLocation")
        concepts = article.get("concepts") or []
        categories = article.get("categories") or []
        extracted_dates = article.get("extractedDates") or article.get("dates") or []
        event_uri = article.get("eventUri") or article.get("eventURI") or article.get("event")
        image_url = article.get("image") or article.get("image_url") or article.get("urlToImage")

        keywords_val = article.get("keywords", "")
        if isinstance(keywords_val, list):
            keywords_val = ", ".join(str(x).strip() for x in keywords_val if str(x).strip())

        return {
            "title": title,
            "content": body,
            "description": article.get("description", ""),
            "snippet": snippet,
            "keywords": keywords_val if isinstance(keywords_val, str) else str(keywords_val or ""),
            "source": {"name": source_name} if source_name else source,
            "url": article.get("url") or article.get("uri", ""),
            "url_to_image": image_url or "",
            "image_url": image_url or "",
            "published_at": article.get("dateTimePub") or article.get("date") or article.get("published_at"),
            "publishedAt": article.get("dateTimePub") or article.get("date") or article.get("published_at"),
            "uuid": article.get("uuid", ""),
            "language": article.get("language", ""),
            "event_uri": event_uri or "",
            "concepts": json.dumps(concepts, ensure_ascii=False) if isinstance(concepts, (list, dict)) else str(concepts or ""),
            "categories": json.dumps(categories, ensure_ascii=False) if isinstance(categories, (list, dict)) else str(categories or ""),
            "location": json.dumps(location, ensure_ascii=False) if isinstance(location, (list, dict)) else str(location or ""),
            "extracted_dates": json.dumps(extracted_dates, ensure_ascii=False) if isinstance(extracted_dates, (list, dict)) else str(extracted_dates or ""),
            "source_rank_percentile": article.get("sourceRankPercentile"),
            "incident_sentence": "",
            "event_type_uri": "",
            "full_text": body,
        }

    async def _wait_for_rate_limit(self):
        try:
            now = asyncio.get_running_loop().time()
            if self._resume_requests_at > now:
                await asyncio.sleep(self._resume_requests_at - now)
            await self.rate_limiter.wait_if_needed_async()
        except Exception as e:
            logger.error("Rate limiter wait failed: %s", e)
            raise

    @staticmethod
    def _parse_int_header(headers: Any, key: str) -> Optional[int]:
        if not headers:
            return None
        value = headers.get(key)
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _target_rps_from_limit(cls, limit_per_window: int, headroom: float) -> Optional[float]:
        if limit_per_window <= 0:
            return None
        if headroom <= 0:
            return None
        return (limit_per_window / RATE_LIMIT_WINDOW_SECONDS) * headroom

    def _adapt_rate_limit_from_headers(self, headers: Any) -> None:
        limit = self._parse_int_header(headers, "X-RateLimit-Limit")
        remaining = self._parse_int_header(headers, "X-RateLimit-Remaining")
        reset_seconds = self._parse_int_header(headers, "X-RateLimit-Reset")

        target_rps = None
        if limit is not None:
            target_rps = self._target_rps_from_limit(limit, self.rate_limit_headroom)
        if remaining is not None and reset_seconds is not None and reset_seconds > 0:
            remaining_rps = remaining / reset_seconds
            if target_rps is None:
                target_rps = remaining_rps
            else:
                target_rps = min(target_rps, remaining_rps)

        if target_rps is None:
            return

        bounded_rps = max(self.min_requests_per_second, min(self.max_requests_per_second, target_rps))
        self.rate_limiter.requests_per_second = bounded_rps

    def _set_resume_from_headers(self, headers: Any) -> None:
        if not headers:
            return

        retry_after = self._parse_int_header(headers, "Retry-After")
        if retry_after is not None and retry_after > 0:
            wait_seconds = retry_after
        else:
            reset_seconds = self._parse_int_header(headers, "X-RateLimit-Reset")
            if reset_seconds is None or reset_seconds <= 0:
                wait_seconds = 1
            else:
                wait_seconds = reset_seconds

        now = asyncio.get_running_loop().time()
        self._resume_requests_at = max(self._resume_requests_at, now + wait_seconds)

    async def fetch_all_articles(
        self,
        search_terms: List[Dict],
        date_params: Optional[Dict[str, str]] = None,
    ) -> List[Dict]:
        if not isinstance(search_terms, list):
            logger.error("fetch_all_articles expected list search_terms, got %s", type(search_terms).__name__)
            return []
        if not search_terms:
            return []

        all_articles = []
        for term in search_terms:
            if not isinstance(term, dict):
                logger.warning("Skipping invalid search term entry: %r", term)
                continue
            if self.rate_limited:
                logger.warning("Rate limit reached after processing %s articles.", len(all_articles))
                logger.warning("Skipping remaining %s terms.", len(search_terms) - len(self.partial_results))
                return all_articles

            term_name = term.get("term", "")
            articles = await self._fetch_for_term(term_name, date_params)
            mention_map: Dict[str, Dict[str, str]] = {}
            self.partial_results.append(term_name)

            if articles:
                for article in articles:
                    normalized = await self._enrich_article_data(
                        raw_article=article,
                        search_term_id=term.get("id"),
                        mention_map=mention_map,
                        preserve_existing_mention_values=False,
                        query_term=term.get("term", ""),
                        query_language=term.get("language", ""),
                        root_term=term.get("root_term", term.get("term", "")),
                    )
                    if not normalized:
                        continue
                    all_articles.append(normalized)

        return all_articles

    def _build_search_query(self, term: str) -> str:
        """
        Build TheNewsAPI search query from user-entered syntax.

        TheNewsAPI supports operators such as +, -, | and quoted phrases.
        We preserve those operators while normalizing whitespace and legacy
        bracket syntax to standard parentheses.
        """
        raw = str(term or "").strip()
        if not raw:
            return ""

        normalized = raw.replace("[", "(").replace("]", ")")
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_source_allowed(self, article_data: Dict[str, Any]) -> bool:
        """Apply source allow/block filters using article URL domain."""
        if not self.source_allowlist and not self.source_blocklist:
            return True

        url = str(article_data.get("url", "") or "")
        domain = self._normalize_domain(urlparse(url).netloc)
        if not domain:
            return not bool(self.source_allowlist)

        if self.source_blocklist and domain in self.source_blocklist:
            return False
        if self.source_allowlist and domain not in self.source_allowlist:
            return False
        return True

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        return normalize_domain(domain)

    @classmethod
    def _parse_csv_list(cls, value: Any) -> set:
        return parse_csv_domain_list(value)

    def _resolve_date_filters(
        self,
        date_params: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """Normalize date filters for TheNewsAPI."""
        today = datetime.now(timezone.utc).date()

        if date_params is None:
            return {
                "published_after": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
                "published_before": today.strftime("%Y-%m-%d"),
            }

        if not date_params:
            return {}

        after = date_params.get("published_after")
        before = date_params.get("published_before")
        specific = date_params.get("published_on")

        if specific:
            return {"published_on": specific}

        filters = {}
        if after:
            filters["published_after"] = after
        if before:
            filters["published_before"] = before
        return filters
