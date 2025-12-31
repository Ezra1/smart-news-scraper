import pytest
from dataclasses import asdict

from src.analysis_utils import (
    analyze_relevance_results,
    calculate_relevance_stats,
)


def test_analyze_relevance_results_basic():
    results = analyze_relevance_results(3, 2, 0.8)
    assert results["relevant_count"] == 3
    assert results["irrelevant_count"] == 2
    assert results["total"] == 5
    assert results["relevant_percentage_str"] == "60.00%"
    assert results["irrelevant_percentage_str"] == "40.00%"
    assert results["relevance_ratio_str"] == "1.50"
    assert results["max_score"] == 0.8
    assert results["conclusion"].startswith("✅")


def test_analyze_relevance_results_no_articles():
    results = analyze_relevance_results(0, 0, 0.0)
    assert results == {
        "relevant_count": 0,
        "irrelevant_count": 0,
        "total": 0,
        "relevance_rate": 0.0,
        "relevant_percentage": 0.0,
        "irrelevant_percentage": 0.0,
        "relevance_ratio": 0.0,
        "max_score": 0.0,
        "conclusion": "⚠️ No articles processed.",
        "relevant_percentage_str": "0.00%",
        "irrelevant_percentage_str": "0.00%",
        "relevance_ratio_str": "0.00",
    }


def test_stats_consistency():
    """Both entry points produce identical results."""
    stats = calculate_relevance_stats(5, 3, 0.9)
    stats_dict = asdict(stats)
    wrapper_dict = analyze_relevance_results(5, 3, 0.9)
    assert stats_dict == wrapper_dict


def test_mixin_delegates_to_utils():
    """ArticleAnalysisMixin delegates to calculate_relevance_stats."""
    from src.analysis_base import ArticleAnalysisMixin

    class Dummy(ArticleAnalysisMixin):
        pass

    dummy = Dummy()
    dummy.relevant = 4
    dummy.irrelevant = 1
    dummy.max_relevance_score = 0.7

    mixin_results = dummy.analyze_results()
    stats_dict = asdict(calculate_relevance_stats(4, 1, 0.7))

    assert mixin_results == stats_dict

