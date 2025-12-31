import pytest

from src.database_manager import DatabaseManager, ArticleManager
from src.insert_processed_articles import RelevanceFilter


def test_relevance_filter_counts_irrelevant(tmp_path, monkeypatch):
    # Reset the singleton so we can use an isolated test database
    monkeypatch.setattr(DatabaseManager, "_instance", None)

    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(str(db_path))
    article_manager = ArticleManager(db_manager)

    # Insert two raw articles
    article_id_relevant = article_manager.insert_article(
        {
            "title": "Secure supply chain",
            "content": "Details about secure pharma supply chain",
            "url": "https://example.com/relevant",
            "source": "TestSource",
            "published_at": "2025-01-01",
        }
    )
    article_id_irrelevant = article_manager.insert_article(
        {
            "title": "Unrelated news",
            "content": "Sports update",
            "url": "https://example.com/irrelevant",
            "source": "TestSource",
            "published_at": "2025-01-02",
        }
    )

    # Record processing results for both articles
    assert article_id_relevant is not None
    assert article_id_irrelevant is not None
    article_manager.record_processing_result(article_id_relevant, 0.9, "relevant")
    article_manager.record_processing_result(article_id_irrelevant, 0.1, "irrelevant")

    # Run the relevance filter against the database source of truth
    relevance_filter = RelevanceFilter(article_manager)
    relevance_filter.process_latest_results()

    stats = article_manager.get_relevance_stats()
    assert relevance_filter.relevant == 1
    assert relevance_filter.irrelevant == 1
    assert stats["relevant"] == 1
    assert stats["irrelevant"] == 1
    assert stats["total"] == 2

    db_manager.close()


def test_relevance_counts_accurate(tmp_path, monkeypatch):
    """Verify relevant + irrelevant totals match processing inputs."""
    monkeypatch.setattr(DatabaseManager, "_instance", None)

    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(str(db_path))
    article_manager = ArticleManager(db_manager)

    total_articles = 10
    relevant_ids = []
    irrelevant_ids = []

    for idx in range(total_articles):
        article_id = article_manager.insert_article(
            {
                "title": f"Article {idx}",
                "content": f"Content {idx}",
                "url": f"https://example.com/{idx}",
                "source": "TestSource",
                "published_at": "2025-01-01",
            }
        )
        assert article_id is not None
        status = "relevant" if idx < total_articles / 2 else "irrelevant"
        score = 0.9 if status == "relevant" else 0.1
        article_manager.record_processing_result(article_id, score, status)
        (relevant_ids if status == "relevant" else irrelevant_ids).append(article_id)

    relevance_filter = RelevanceFilter(article_manager)
    relevance_filter.process_latest_results()
    results = relevance_filter.analyze_results()

    assert results["relevant_count"] == len(relevant_ids)
    assert results["irrelevant_count"] == len(irrelevant_ids)
    assert results["total"] == total_articles

    db_manager.close()

