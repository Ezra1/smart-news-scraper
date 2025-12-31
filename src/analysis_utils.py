"""Utility functions for analyzing article relevance results."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Union

from src.logger_config import setup_logging

logger = setup_logging(__name__)


@dataclass
class RelevanceStats:
    """Canonical relevance statistics payload."""

    relevant_count: int
    irrelevant_count: int
    total: int
    relevance_rate: float  # 0.0–1.0
    relevant_percentage: float
    irrelevant_percentage: float
    relevance_ratio: float
    max_score: float
    conclusion: str
    relevant_percentage_str: str
    irrelevant_percentage_str: str
    relevance_ratio_str: str


def _format_ratio(relevant: int, irrelevant: int) -> float:
    if irrelevant == 0:
        return float("inf") if relevant > 0 else 0.0
    return relevant / irrelevant


def _conclusion(relevant_percentage: float) -> str:
    return (
        "✅ Most articles are relevant, indicating well-targeted search."
        if relevant_percentage > 50
        else "⚠️ Most articles are irrelevant, suggesting search criteria refinement needed."
    )


def calculate_relevance_stats(
    relevant: int,
    irrelevant: int,
    max_score: float = 0.0,
) -> RelevanceStats:
    """Canonical relevance statistics calculation."""
    total = relevant + irrelevant
    if total == 0:
        logger.warning("⚠️ No articles processed.")
        return RelevanceStats(
            relevant_count=0,
            irrelevant_count=0,
            total=0,
            relevance_rate=0.0,
            relevant_percentage=0.0,
            irrelevant_percentage=0.0,
            relevance_ratio=0.0,
            max_score=0.0,
            conclusion="⚠️ No articles processed.",
            relevant_percentage_str="0.00%",
            irrelevant_percentage_str="0.00%",
            relevance_ratio_str="0.00",
        )

    relevant_pct = (relevant / total) * 100
    irrelevant_pct = (irrelevant / total) * 100
    ratio = _format_ratio(relevant, irrelevant)

    return RelevanceStats(
        relevant_count=relevant,
        irrelevant_count=irrelevant,
        total=total,
        relevance_rate=relevant / total,
        relevant_percentage=relevant_pct,
        irrelevant_percentage=irrelevant_pct,
        relevance_ratio=ratio,
        max_score=max_score,
        conclusion=_conclusion(relevant_pct),
        relevant_percentage_str=f"{relevant_pct:.2f}%",
        irrelevant_percentage_str=f"{irrelevant_pct:.2f}%",
        relevance_ratio_str=f"{ratio:.2f}" if ratio != float("inf") else "inf",
    )


def analyze_relevance_results(
    relevant: int, irrelevant: int, max_relevance_score: float
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper returning a dict instead of a dataclass.
    """
    stats = calculate_relevance_stats(relevant, irrelevant, max_relevance_score)
    return asdict(stats)


def print_analysis_results(analysis_results: Union[RelevanceStats, Mapping[str, Any]]) -> None:
    """
    Print analysis results in a formatted way.
    """
    stats_dict: Mapping[str, Any] = (
        asdict(analysis_results) if isinstance(analysis_results, RelevanceStats) else analysis_results
    )

    # Prefer preformatted strings when available
    relevant_percentage = stats_dict.get("relevant_percentage_str", stats_dict.get("relevant_percentage"))
    irrelevant_percentage = stats_dict.get("irrelevant_percentage_str", stats_dict.get("irrelevant_percentage"))
    relevance_ratio = stats_dict.get("relevance_ratio_str", stats_dict.get("relevance_ratio"))

    logger.info(f"Relevant articles: {stats_dict.get('relevant_count')}")
    logger.info(f"Irrelevant articles: {stats_dict.get('irrelevant_count')}")
    logger.info(f"Total articles: {stats_dict.get('total')}")
    logger.info(f"Relevant percentage: {relevant_percentage}")
    logger.info(f"Irrelevant percentage: {irrelevant_percentage}")
    logger.info(f"Relevance ratio: {relevance_ratio}")
    logger.info(f"Max relevance score: {stats_dict.get('max_score')}")
    logger.info(stats_dict.get("conclusion"))

    print(f"Relevant articles: {stats_dict.get('relevant_count')}")
    print(f"Irrelevant articles: {stats_dict.get('irrelevant_count')}")
    print(f"Total articles: {stats_dict.get('total')}")
    print(f"Relevant percentage: {relevant_percentage}")
    print(f"Irrelevant percentage: {irrelevant_percentage}")
    print(f"Relevance ratio: {relevance_ratio}")
    print(f"Max relevance score: {stats_dict.get('max_score')}")
    print(stats_dict.get("conclusion"))