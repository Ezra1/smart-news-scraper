import aiohttp
import asyncio
import json
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from src.database_manager import ArticleManager, DatabaseManager
from src.logger_config import setup_logging
from src.incident_filter import is_incident_article
from src.url_content_extractor import fetch_readable_text

logger = setup_logging(__name__)

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.config import ConfigManager
from src.utils.rate_limiter import RateLimiter

CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

PHARMA_SECURITY_EVENT_TYPES = [
    "et/crime/counterfeit-goods",
    "et/crime/arrest",
    "et/crime/raid",
    "et/business/recalls",
    "et/health/disease/outbreak",
    "et/politics/sanctions",
]


class NewsArticleScraper:
    """Fetch and enrich articles using Event Registry."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db_manager: Optional[DatabaseManager] = None,
        db_path: Optional[str] = None,
    ):
        self.config = config_manager
        self.api_key = self.config.get("NEWS_API_KEY")
        self.api_url = self.config.get(
            "NEWS_API_URL",
            "https://eventregistry.org/api/v1/article/getArticles",
        )
        self.mentions_url = self.config.get(
            "EVENT_REGISTRY_MENTIONS_URL",
            "https://eventregistry.org/api/v1/article/getMentions",
        )
        self.rate_limited = False
        self.partial_results = []
        self.event_type_uris = list(PHARMA_SECURITY_EVENT_TYPES)

        self.db_manager = db_manager or DatabaseManager(db_path or "news_articles.db")
        self.article_manager = ArticleManager(self.db_manager)

        requests_per_second = config_manager.get("NEWS_API_REQUESTS_PER_SECOND", 1)
        self.rate_limiter = RateLimiter(requests_per_second=requests_per_second)
        self.articles_count = int(self.config.get("EVENT_REGISTRY_ARTICLES_COUNT", 100))
        self.mentions_count = int(self.config.get("EVENT_REGISTRY_MENTIONS_COUNT", 100))
        self.source_rank_start = int(self.config.get("EVENT_REGISTRY_SOURCE_RANK_START", 0))
        self.source_rank_end = int(self.config.get("EVENT_REGISTRY_SOURCE_RANK_END", 50))
        self.duplicate_filter = self.config.get(
            "EVENT_REGISTRY_DUPLICATE_FILTER",
            "skipDuplicates",
        )
        self.min_body_length = int(self.config.get("EVENT_REGISTRY_MIN_BODY_LENGTH", 600))
        self.enable_url_fallback = bool(self.config.get("EVENT_REGISTRY_ENABLE_URL_FALLBACK", True))

    async def fetch_articles(
        self,
        search_terms: List[str],
        search_term_map: Dict[str, int],
        date_params: Optional[Dict[str, str]] = None,
    ) -> List[dict]:
        """Fetch and process articles for search terms."""
        all_articles = []
        self.rate_limited = False

        for term in search_terms:
            try:
                raw_articles = await self._fetch_for_term(term, date_params)
                if self.rate_limited:
                    break

                mention_map = await self._fetch_mentions_for_term(term, date_params)
                for raw in raw_articles:
                    article_data = self._normalize_article(raw)
                    article_data["search_term_id"] = search_term_map.get(term)
                    article_data["event_type_uri"] = article_data.get("event_type_uri") or mention_map.get(
                        article_data.get("url", ""),
                        {},
                    ).get("event_type_uri", "")
                    article_data["incident_sentence"] = article_data.get("incident_sentence") or mention_map.get(
                        article_data.get("url", ""),
                        {},
                    ).get("incident_sentence", "")

                    await self._maybe_apply_url_fallback(article_data)
                    title = article_data.get("title", "")
                    content = article_data.get("content", "")
                    article_data["incident_level"] = is_incident_article(f"{title} {content}")[0]

                    article_id = self.article_manager.insert_article(article_data)
                    if article_id:
                        article_data["id"] = article_id
                        all_articles.append(article_data)

                logger.info("Processed %s Event Registry articles for term '%s'", len(raw_articles), term)
            except Exception as e:
                logger.error("Error processing articles for term '%s': %s", term, e)
        return all_articles

    async def _fetch_for_term(
        self,
        term: str,
        date_params: Optional[Dict[str, str]] = None,
    ) -> List[Dict]:
        logger.info("Fetching articles for term: %s", term)
        try:
            date_filters = self._resolve_date_filters(date_params)
            all_articles: List[Dict] = []
            max_pages = 5

            for page in range(1, max_pages + 1):
                await self._wait_for_rate_limit()
                payload = self._build_articles_payload(term, page, date_filters)
                page_articles = await self._make_api_request(payload)
                if not page_articles:
                    break
                all_articles.extend(page_articles)
                if len(page_articles) < self.articles_count:
                    break

            logger.info("Found %s articles for term: %s", len(all_articles), term)
            return all_articles
        except Exception as e:
            logger.error("Error fetching articles for term '%s': %s", term, e)
            return []

    def _build_articles_payload(self, term: str, page: int, date_filters: Dict[str, str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "action": "getArticles",
            "apiKey": self.api_key,
            "resultType": "articles",
            "articlesPage": page,
            "articlesCount": self.articles_count,
            "articlesSortBy": "date",
            "articlesSortByAsc": False,
            "keyword": self.build_search_query([term]),
            "keywordLoc": "body,title",
            "lang": "eng",
            "includeArticleTitle": True,
            "includeArticleBasicInfo": True,
            "includeArticleBody": True,
            "articleBodyLen": -1,
            "includeArticleEventUri": True,
            "includeArticleConcepts": True,
            "includeArticleCategories": True,
            "includeArticleLocation": True,
            "includeArticleExtractedDates": True,
            "isDuplicateFilter": self.duplicate_filter,
            "startSourceRankPercentile": self.source_rank_start,
            "endSourceRankPercentile": self.source_rank_end,
        }
        payload.update(date_filters)
        return payload

    async def _make_api_request(self, payload: dict) -> List[dict]:
        """Make request to Event Registry getArticles."""
        try:
            async with aiohttp.ClientSession(timeout=CLIENT_TIMEOUT, trust_env=True) as session:
                async with session.post(self.api_url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._extract_articles_from_response(data)
                    if response.status in (402, 429):
                        logger.warning("Rate limit/plan limit exceeded for Event Registry")
                        self.rate_limited = True
                        return []
                    if response.status == 401:
                        logger.error("Invalid Event Registry API key")
                        return []
                    response_text = await response.text()
                    logger.error(
                        "Event Registry request failed with status %s | payload=%s | response=%s",
                        response.status,
                        payload,
                        response_text,
                    )
                    return []
        except asyncio.TimeoutError:
            logger.error("Event Registry request timed out")
            return []
        except Exception as e:
            logger.error("Event Registry request error: %s", e)
            return []

    def _extract_articles_from_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        if isinstance(data.get("articles"), dict):
            results = data["articles"].get("results", [])
            return results if isinstance(results, list) else []
        if isinstance(data.get("articles"), list):
            return data.get("articles", [])
        if isinstance(data.get("results"), list):
            return data["results"]
        return []

    async def _fetch_mentions_for_term(
        self,
        term: str,
        date_params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Dict[str, str]]:
        """Fetch mention sentences by fixed event types and map them by article URL."""
        date_filters = self._resolve_date_filters(date_params)
        payload: Dict[str, Any] = {
            "apiKey": self.api_key,
            "resultType": "mentions",
            "mentionsPage": 1,
            "mentionsCount": self.mentions_count,
            "mentionsSortBy": "date",
            "mentionsSortByAsc": False,
            "keyword": term,
            "eventTypeUri": self.event_type_uris,
            "lang": "eng",
            "showDuplicates": False,
        }
        payload.update(date_filters)

        try:
            await self._wait_for_rate_limit()
            async with aiohttp.ClientSession(timeout=CLIENT_TIMEOUT, trust_env=True) as session:
                async with session.post(self.mentions_url, json=payload) as response:
                    if response.status != 200:
                        return {}
                    data = await response.json()
        except Exception as e:
            logger.warning("Event Registry mentions request failed for term '%s': %s", term, e)
            return {}

        mapping: Dict[str, Dict[str, str]] = {}
        for mention in self._extract_mentions_from_response(data):
            url = self._extract_mention_article_url(mention)
            sentence = self._extract_mention_sentence(mention)
            event_type_uri = self._extract_mention_event_type(mention)
            if url and sentence and url not in mapping:
                mapping[url] = {
                    "incident_sentence": sentence,
                    "event_type_uri": event_type_uri,
                }
        return mapping

    def _extract_mentions_from_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        if isinstance(data.get("mentions"), dict):
            results = data["mentions"].get("results", [])
            return results if isinstance(results, list) else []
        if isinstance(data.get("mentions"), list):
            return data["mentions"]
        if isinstance(data.get("results"), list):
            return data["results"]
        return []

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
        content = str(article_data.get("content", "") or "")
        if not self.enable_url_fallback or len(content) >= self.min_body_length:
            article_data["body_source"] = "event_registry"
            return

        fallback_text, status = await fetch_readable_text(
            article_data.get("url", ""),
            min_length=self.min_body_length,
        )
        article_data["url_fallback_status"] = status
        if fallback_text and len(fallback_text) > len(content):
            article_data["content"] = fallback_text
            article_data["full_text"] = fallback_text
            article_data["body_source"] = "url_fallback"
        else:
            article_data["body_source"] = "event_registry"

    def _normalize_article(self, article: Dict[str, Any]) -> Dict[str, Any]:
        title = article.get("title") or article.get("articleTitle") or ""
        body = article.get("body") or article.get("content") or article.get("description") or ""
        snippet = article.get("snippet") or ""
        if not body and snippet:
            body = snippet
        if not body:
            body = title

        source = article.get("source") or {}
        if isinstance(source, dict):
            source_name = source.get("title") or source.get("name") or ""
        else:
            source_name = str(source)

        location = article.get("location") or article.get("articleLocation")
        concepts = article.get("concepts") or []
        categories = article.get("categories") or []
        extracted_dates = article.get("extractedDates") or article.get("dates") or []
        event_uri = article.get("eventUri") or article.get("eventURI") or article.get("event")
        image_url = article.get("image") or article.get("image_url") or article.get("urlToImage")

        return {
            "title": title,
            "content": body,
            "description": article.get("description", ""),
            "snippet": snippet,
            "source": {"name": source_name} if source_name else source,
            "url": article.get("url") or article.get("uri", ""),
            "url_to_image": image_url or "",
            "image_url": image_url or "",
            "published_at": article.get("dateTimePub") or article.get("date") or article.get("published_at"),
            "publishedAt": article.get("dateTimePub") or article.get("date") or article.get("published_at"),
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
        await self.rate_limiter.wait_if_needed_async()

    async def fetch_all_articles(
        self,
        search_terms: List[Dict],
        date_params: Optional[Dict[str, str]] = None,
    ) -> List[Dict]:
        all_articles = []
        for term in search_terms:
            if self.rate_limited:
                logger.warning("Rate limit reached after processing %s articles.", len(all_articles))
                logger.warning("Skipping remaining %s terms.", len(search_terms) - len(self.partial_results))
                return all_articles

            term_name = term.get("term", "")
            articles = await self._fetch_for_term(term_name, date_params)
            mention_map = await self._fetch_mentions_for_term(term_name, date_params)
            self.partial_results.append(term_name)

            if articles:
                for article in articles:
                    normalized = self._normalize_article(article)
                    normalized["search_term_id"] = term.get("id")
                    normalized["event_type_uri"] = mention_map.get(normalized.get("url", ""), {}).get(
                        "event_type_uri",
                        "",
                    )
                    normalized["incident_sentence"] = mention_map.get(normalized.get("url", ""), {}).get(
                        "incident_sentence",
                        "",
                    )
                    await self._maybe_apply_url_fallback(normalized)
                    all_articles.append(normalized)

        return all_articles

    def build_search_query(self, base_terms: List[str]) -> str:
        incident_boost = "(seized | arrested | raided | smuggling | counterfeit | recall)"
        base = " | ".join(base_terms)
        query = f"({base}) ({incident_boost} | {base})"
        query += " -opinion -editorial -commentary -analysis"
        return query

    def _resolve_date_filters(
        self,
        date_params: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """Normalize date filters for Event Registry."""
        today = datetime.now(timezone.utc).date()

        if date_params is None:
            return {
                "dateStart": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
                "dateEnd": today.strftime("%Y-%m-%d"),
            }

        if not date_params:
            return {}

        after = date_params.get("published_after") if date_params else None
        before = date_params.get("published_before") if date_params else None
        specific = date_params.get("published_on") if date_params else None

        if specific:
            return {"dateStart": specific, "dateEnd": specific}

        filters = {}
        if after:
            filters["dateStart"] = after
        if before:
            filters["dateEnd"] = before
        return filters
