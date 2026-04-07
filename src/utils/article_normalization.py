"""Shared normalization helpers for domains, source labels, and config lists."""

from typing import Any, Iterable, Set


def normalize_domain(domain: str) -> str:
    """Normalize a domain value for allow/block list comparisons."""
    normalized = str(domain or "").strip().lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return normalized


def parse_csv_domain_list(value: Any) -> Set[str]:
    """Parse comma-separated or iterable domain values into a normalized set."""
    if not value:
        return set()

    if isinstance(value, (list, tuple, set)):
        raw_values: Iterable[Any] = value
    else:
        raw_values = str(value).split(",")

    return {
        normalize_domain(str(item).strip())
        for item in raw_values
        if str(item).strip()
    }


def extract_source_name(source_value: Any, default: str = "") -> str:
    """Extract a consistent source string from dict-or-string source fields."""
    if isinstance(source_value, dict):
        source_name = source_value.get("name") or source_value.get("title") or default
        return str(source_name or default)
    return str(source_value or default)
