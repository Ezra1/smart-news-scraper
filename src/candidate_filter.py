"""Pre-LLM candidate filtering with high-recall heuristics and stage stats."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urlparse

from src.database_manager import ArticleManager, DatabaseManager
from src.incident_filter import is_incident_article
from src.logger_config import setup_logging
from src.utils.article_normalization import (
    extract_source_name,
    normalize_domain,
    parse_csv_domain_list,
)

logger = setup_logging(__name__)


WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-]{1,}", re.IGNORECASE)


class SemanticScorer(Protocol):
    """Optional middle-layer scorer contract (Stage 3)."""

    def rank(
        self,
        candidates: List[Dict[str, Any]],
        query_terms_by_id: Dict[int, str],
    ) -> List[Dict[str, Any]]:
        ...


class NoOpSemanticScorer:
    """Default semantic scorer that preserves candidate ordering."""

    def rank(
        self,
        candidates: List[Dict[str, Any]],
        query_terms_by_id: Dict[int, str],
    ) -> List[Dict[str, Any]]:
        return candidates


@dataclass
class FilterStats:
    retrieved_count: int = 0
    after_heuristics_count: int = 0
    after_semantic_count: int = 0
    sent_to_llm_count: int = 0


class CandidateFilter:
    """Apply conservative pre-LLM filtering and record drop reasons."""

    def __init__(
        self,
        config_manager,
        db_manager: Optional[DatabaseManager] = None,
        article_manager: Optional[ArticleManager] = None,
        semantic_scorer: Optional[SemanticScorer] = None,
    ):
        self.config = config_manager
        self.db_manager = db_manager or DatabaseManager()
        self.article_manager = article_manager or ArticleManager(self.db_manager)
        self.semantic_scorer = semantic_scorer or NoOpSemanticScorer()

        self.enable_filtering = bool(self.config.get("PRELLM_ENABLE_FILTERING", True))
        self.min_content_chars = int(self.config.get("PRELLM_MIN_CONTENT_CHARS", 120))
        self.max_content_chars = int(self.config.get("PRELLM_MAX_CONTENT_CHARS", 20000))
        self.min_query_token_overlap = int(self.config.get("PRELLM_MIN_QUERY_TOKEN_OVERLAP", 1))
        self.require_incident_signal = bool(self.config.get("PRELLM_REQUIRE_INCIDENT_SIGNAL", False))
        self.dedup_by_url = bool(self.config.get("PRELLM_DEDUP_BY_URL", True))
        self.dedup_by_title = bool(self.config.get("PRELLM_DEDUP_BY_TITLE", True))
        self.top_k_per_term = int(self.config.get("PRELLM_TOP_K_PER_TERM", 100))
        self.stage3_enabled = bool(self.config.get("PRELLM_STAGE3_ENABLED", False))
        self.log_drops = bool(self.config.get("PRELLM_LOG_DROPS", True))
        self.source_allowlist = self._parse_csv_list(self.config.get("NEWS_SOURCE_ALLOWLIST", ""))
        self.source_blocklist = self._parse_csv_list(self.config.get("NEWS_SOURCE_BLOCKLIST", ""))

    def filter_candidates(
        self,
        articles: List[Dict[str, Any]],
        query_terms_by_id: Dict[int, str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Run Stage 2 and optional Stage 3 filtering."""
        stats = FilterStats(retrieved_count=len(articles))
        dropped_by_reason: Dict[str, int] = defaultdict(int)

        if not self.enable_filtering:
            stats.after_heuristics_count = len(articles)
            stats.after_semantic_count = len(articles)
            stats.sent_to_llm_count = len(articles)
            return articles, self._stats_payload(stats, dropped_by_reason)

        seen_urls = set()
        seen_title_hashes = set()
        heuristic_candidates: List[Dict[str, Any]] = []

        for article in articles:
            keep, reason, details = self._evaluate_article(
                article,
                query_terms_by_id=query_terms_by_id,
                seen_urls=seen_urls,
                seen_title_hashes=seen_title_hashes,
            )
            self._record_decision(article, keep=keep, reason=reason, details=details)
            if keep:
                heuristic_candidates.append(article)
            else:
                dropped_by_reason[reason] += 1

        heuristic_candidates = self._apply_top_k_per_term(heuristic_candidates, dropped_by_reason)
        stats.after_heuristics_count = len(heuristic_candidates)

        semantic_candidates = heuristic_candidates
        if self.stage3_enabled:
            semantic_candidates = self.semantic_scorer.rank(heuristic_candidates, query_terms_by_id)
        stats.after_semantic_count = len(semantic_candidates)
        stats.sent_to_llm_count = len(semantic_candidates)

        return semantic_candidates, self._stats_payload(stats, dropped_by_reason)

    def _evaluate_article(
        self,
        article: Dict[str, Any],
        query_terms_by_id: Dict[int, str],
        seen_urls: set,
        seen_title_hashes: set,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        title = str(article.get("title", "") or "").strip()
        content = str(article.get("content", "") or "").strip()
        url = str(article.get("url", "") or "").strip()
        source_name = self._source_name(article.get("source"))
        domain = self._normalize_domain(urlparse(url).netloc)

        if not title or not content or not url:
            return False, "missing_required_fields", {"domain": domain}

        if self.source_blocklist and domain in self.source_blocklist:
            return False, "blocked_source", {"domain": domain}
        if self.source_allowlist and domain not in self.source_allowlist:
            return False, "not_in_allowlist", {"domain": domain}

        content_len = len(content)
        if content_len < self.min_content_chars:
            return False, "too_short", {"content_len": content_len, "domain": domain}
        if content_len > self.max_content_chars:
            return False, "too_long", {"content_len": content_len, "domain": domain}

        if self.dedup_by_url:
            if url in seen_urls:
                return False, "duplicate_url", {"domain": domain}
            seen_urls.add(url)

        if self.dedup_by_title:
            title_hash = hashlib.sha1(self._normalize_text(title).encode("utf-8")).hexdigest()
            if title_hash in seen_title_hashes:
                return False, "duplicate_title", {"domain": domain}
            seen_title_hashes.add(title_hash)

        query_tokens = self._query_tokens(article, query_terms_by_id)
        article_tokens = self._tokens(f"{title} {content}")
        token_overlap = len(query_tokens & article_tokens) if query_tokens else 0
        if query_tokens and token_overlap < self.min_query_token_overlap:
            return False, "no_overlap", {"overlap": token_overlap, "domain": domain}

        is_incident, has_enforcement, has_pharma = is_incident_article(f"{title} {content}")
        if self.require_incident_signal and not is_incident:
            return False, "no_incident_signal", {"domain": domain}

        overlap_ratio = (
            float(token_overlap) / float(max(1, len(query_tokens)))
            if query_tokens
            else 0.0
        )
        heuristic_score = round(
            overlap_ratio
            + (0.4 if is_incident else 0.0)
            + (0.2 if has_enforcement else 0.0)
            + (0.2 if has_pharma else 0.0),
            4,
        )

        article["prellm_domain"] = domain
        article["prellm_query_token_overlap"] = token_overlap
        article["prellm_overlap_ratio"] = overlap_ratio
        article["prellm_incident_signal"] = bool(is_incident)
        article["prellm_heuristic_score"] = heuristic_score
        article["prellm_source_name"] = source_name
        return True, "kept", {"heuristic_score": heuristic_score, "domain": domain}

    def _apply_top_k_per_term(
        self,
        candidates: List[Dict[str, Any]],
        dropped_by_reason: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        if self.top_k_per_term <= 0:
            return candidates

        buckets: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        for article in candidates:
            buckets[article.get("search_term_id")].append(article)

        trimmed: List[Dict[str, Any]] = []
        for _, items in buckets.items():
            sorted_items = sorted(
                items,
                key=lambda a: float(a.get("prellm_heuristic_score", 0.0)),
                reverse=True,
            )
            kept = sorted_items[: self.top_k_per_term]
            dropped = sorted_items[self.top_k_per_term :]
            trimmed.extend(kept)
            for article in dropped:
                dropped_by_reason["top_k_trim"] += 1
                self._record_decision(article, keep=False, reason="top_k_trim", details={})

        return trimmed

    def _record_decision(
        self,
        article: Dict[str, Any],
        keep: bool,
        reason: str,
        details: Dict[str, Any],
    ) -> None:
        article_id = article.get("id")
        if article_id is None:
            return

        heuristic_score = float(article.get("prellm_heuristic_score", 0.0))
        overlap = int(article.get("prellm_query_token_overlap", 0))
        try:
            self.article_manager.record_pre_llm_filter_result(
                raw_article_id=int(article_id),
                decision="keep" if keep else "drop",
                reason=reason,
                heuristic_score=heuristic_score,
                lexical_overlap=overlap,
                metadata=details,
            )
        except Exception as exc:
            logger.warning("Could not persist pre-LLM decision for article %s: %s", article_id, exc)

        if self.log_drops and not keep:
            logger.info(
                "Pre-LLM drop | article_id=%s reason=%s details=%s",
                article_id,
                reason,
                details,
            )

    def _query_tokens(self, article: Dict[str, Any], query_terms_by_id: Dict[int, str]) -> set:
        term_id = article.get("search_term_id")
        query_term = query_terms_by_id.get(term_id, "")
        if not query_term:
            query_term = " ".join(query_terms_by_id.values())
        return self._tokens(query_term)

    @staticmethod
    def _tokens(text: str) -> set:
        return {m.group(0).lower() for m in WORD_PATTERN.finditer(text or "")}

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip().lower()

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        return normalize_domain(domain)

    @staticmethod
    def _parse_csv_list(value: Any) -> set:
        return parse_csv_domain_list(value)

    @staticmethod
    def _source_name(source_value: Any) -> str:
        return extract_source_name(source_value)

    @staticmethod
    def _stats_payload(stats: FilterStats, dropped_by_reason: Dict[str, int]) -> Dict[str, Any]:
        return {
            "retrieved_count": stats.retrieved_count,
            "after_heuristics_count": stats.after_heuristics_count,
            "after_semantic_count": stats.after_semantic_count,
            "sent_to_llm_count": stats.sent_to_llm_count,
            "dropped_by_reason": dict(dropped_by_reason),
        }
