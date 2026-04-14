from dataclasses import dataclass, field
import re
from typing import Optional


@dataclass
class TermProgress:
    current: int
    total: int
    term: Optional[str] = None
    articles_found: Optional[int] = None


@dataclass
class ArticleProgress:
    current: int
    total: int


@dataclass
class ArticleCounts:
    """fetched: cumulative sum from per-query progress (pre run-level URL dedup)."""

    fetched: Optional[int] = None
    fetched_run_unique: Optional[int] = None


@dataclass
class StatusUpdate:
    message: str
    is_error: bool = False
    is_warning: bool = False
    is_success: bool = False
    term_progress: Optional[TermProgress] = None
    cleaning_progress: Optional[ArticleProgress] = None
    analysis_progress: Optional[ArticleProgress] = None
    cleaning_started: bool = False
    analysis_started: bool = False
    fetch_complete: bool = False
    cleaning_complete: bool = False
    analysis_complete: bool = False
    rate_limited: bool = False
    counts: ArticleCounts = field(default_factory=ArticleCounts)


class StatusParser:
    """Parse raw status strings into structured data for the GUI."""

    TERM_PATTERN = re.compile(r"Processing term\s+(\d+)\s*/\s*(\d+):\s*(.+)")
    ARTICLES_FOUND_PATTERN = re.compile(r"\((\d+)\s+articles\s+found\)")
    COMPLETED_FETCH_PATTERN = re.compile(r"completed fetch:\s*(\d+)\s+articles\b", re.IGNORECASE)
    FRACTION_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)")

    def parse(
        self,
        message: str,
        is_error: bool = False,
        is_warning: bool = False,
        is_success: bool = False,
    ) -> StatusUpdate:
        """Return a StatusUpdate describing the supplied status string."""
        normalized = message.lower()
        update = StatusUpdate(
            message=message,
            is_error=is_error,
            is_warning=is_warning,
            is_success=is_success,
        )

        update.term_progress = self._parse_term_progress(message)

        fetched = self._extract_fetched_count(message)
        if fetched is not None:
            update.counts.fetched = fetched
            if update.term_progress and update.term_progress.articles_found is None:
                update.term_progress.articles_found = fetched

        completed_fetch = self._extract_completed_fetch_unique_count(message)
        if completed_fetch is not None:
            update.counts.fetched_run_unique = completed_fetch

        if self._is_analysis_message(normalized):
            update.analysis_started = True
            progress = self._parse_fraction_progress(message)
            if progress:
                update.analysis_progress = progress
        elif self._is_cleaning_message(normalized):
            update.cleaning_started = True
            progress = self._parse_fraction_progress(message)
            if progress:
                update.cleaning_progress = progress

        if "completed fetch" in normalized and "rate limit" not in normalized:
            update.fetch_complete = True
        if "completed cleaning" in normalized:
            update.cleaning_complete = True
        if "completed analysis" in normalized:
            update.analysis_complete = True
        if "rate limit reached" in normalized:
            update.rate_limited = True

        return update

    def _parse_term_progress(self, message: str) -> Optional[TermProgress]:
        """Parse fetch term progress from messages like:
        'Processing term X/Y: term (Z articles found)'"""
        match = self.TERM_PATTERN.search(message)
        if not match:
            return None

        try:
            current = int(match.group(1))
            total = int(match.group(2))
            remainder = match.group(3)
            term, _, _ = remainder.partition("(")
            articles_found = self._extract_fetched_count(message)
            return TermProgress(
                current=current,
                total=total,
                term=term.strip(),
                articles_found=articles_found,
            )
        except (TypeError, ValueError):
            return None

    def _parse_fraction_progress(self, message: str) -> Optional[ArticleProgress]:
        """Parse progress strings of the form 'X/Y'."""
        fraction = self.FRACTION_PATTERN.search(message)
        if not fraction:
            return None
        try:
            current = int(fraction.group(1))
            total = int(fraction.group(2))
            return ArticleProgress(current=current, total=total)
        except ValueError:
            return None

    def _extract_fetched_count(self, message: str) -> Optional[int]:
        """Pull the '(N articles found)' count from fetch messages."""
        match = self.ARTICLES_FOUND_PATTERN.search(message)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _extract_completed_fetch_unique_count(self, message: str) -> Optional[int]:
        """Parse 'Completed fetch: N articles ...' for post run-dedup URL total."""
        match = self.COMPLETED_FETCH_PATTERN.search(message)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _is_analysis_message(self, normalized: str) -> bool:
        return "analyzing articles" in normalized or normalized.startswith("analyzed ")

    def _is_cleaning_message(self, normalized: str) -> bool:
        return "cleaning articles" in normalized or normalized.startswith("cleaned ")

