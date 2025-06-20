import pytest
from src.analysis_utils import analyze_relevance_results


def test_analyze_relevance_results_basic():
    results = analyze_relevance_results(3, 2, 0.8)
    assert results["Relevant articles"] == 3
    assert results["Irrelevant articles"] == 2
    assert results["Total articles"] == 5
    assert results["Relevant percentage"] == "60.00%"
    assert results["Irrelevant percentage"] == "40.00%"
    assert results["Relevance ratio"] == "1.50"
    assert results["Max relevance score"] == 0.8
    assert results["Conclusion"].startswith("✅")


def test_analyze_relevance_results_no_articles():
    results = analyze_relevance_results(0, 0, 0.0)
    assert results == {
        "Relevant articles": 0,
        "Irrelevant articles": 0,
        "Total articles": 0,
        "Relevant percentage": "0.00%",
        "Irrelevant percentage": "0.00%",
        "Relevance ratio": "0.00",
        "Max relevance score": 0.0,
        "Conclusion": "⚠️ No articles processed.",
    }

