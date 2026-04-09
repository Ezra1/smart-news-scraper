import sqlite3
from queue import Queue

import pytest

from src.database_manager import ArticleManager, DatabaseManager


def _reset_db_singleton():
    DatabaseManager._instance = None
    DatabaseManager._connection_pool = Queue(maxsize=10)


@pytest.fixture
def article_manager(tmp_path):
    _reset_db_singleton()
    db_path = tmp_path / "ingest_test.db"
    db_manager = DatabaseManager(str(db_path))
    manager = ArticleManager(db_manager)
    yield manager, db_manager
    db_manager.close()
    _reset_db_singleton()


def _article_payload(url: str, title: str = "Title") -> dict:
    return {
        "title": title,
        "content": "Content body",
        "url": url,
        "source": "Example Source",
        "published_at": "2026-01-01",
    }


def test_insert_article_duplicate_returns_existing_id(article_manager):
    manager, db = article_manager

    first_id = manager.insert_article(_article_payload("https://example.com/a1", title="First"))
    second_id = manager.insert_article(_article_payload("https://example.com/a1", title="Second"))

    assert first_id is not None
    assert second_id == first_id
    rows = db.execute_query("SELECT COUNT(*) AS c FROM raw_articles WHERE url = ?", ("https://example.com/a1",))
    assert rows[0]["c"] == 1


def test_insert_articles_batch_handles_duplicates(article_manager):
    manager, db = article_manager
    batch = [
        _article_payload("https://example.com/u1", title="One"),
        _article_payload("https://example.com/u2", title="Two"),
        _article_payload("https://example.com/u1", title="One duplicate"),
    ]

    ids = manager.insert_articles_batch(batch)

    assert len(ids) == 3
    assert ids[0] is not None
    assert ids[1] is not None
    assert ids[2] == ids[0]
    rows = db.execute_query("SELECT COUNT(*) AS c FROM raw_articles")
    assert rows[0]["c"] == 2


def test_insert_articles_batch_rolls_back_on_sqlite_error(article_manager, monkeypatch):
    manager, db = article_manager
    batch = [
        _article_payload("https://example.com/r1", title="One"),
        _article_payload("https://example.com/r2", title="Two"),
    ]

    original = manager._raw_insert_values
    state = {"count": 0}

    def broken_values(data):
        state["count"] += 1
        if state["count"] == 2:
            raise sqlite3.Error("forced failure")
        return original(data)

    monkeypatch.setattr(manager, "_raw_insert_values", broken_values)

    ids = manager.insert_articles_batch(batch)

    assert ids == [None, None]
    rows = db.execute_query("SELECT COUNT(*) AS c FROM raw_articles")
    assert rows[0]["c"] == 0
