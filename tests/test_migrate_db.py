"""Tests for database migration script."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from migrate_db import migrate_database


@pytest.fixture
def legacy_db():
    """Create a DB with old schema (cleaned_articles table)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        conn = sqlite3.connect(f.name)
        conn.execute(
            """CREATE TABLE cleaned_articles (
                id INTEGER PRIMARY KEY,
                title TEXT,
                content TEXT,
                relevance_score REAL
            )"""
        )
        conn.execute("INSERT INTO cleaned_articles VALUES (1, 'Test', 'Content', 0.8)")
        conn.execute("INSERT INTO cleaned_articles VALUES (2, 'Test2', 'Content2', 0.9)")
        conn.commit()
        conn.close()
        yield f.name
    Path(f.name).unlink(missing_ok=True)


def _count_rows(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]
    finally:
        conn.close()


def _table_exists(db_path: str, table: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


class TestMigration:
    def test_migration_moves_data(self, legacy_db):
        """Migration should move rows from cleaned_articles to relevant_articles."""
        assert migrate_database(legacy_db)

        assert _table_exists(legacy_db, "relevant_articles")
        assert _count_rows(legacy_db, "relevant_articles") == 2
        assert not _table_exists(legacy_db, "cleaned_articles")

    def test_migration_is_idempotent(self, legacy_db):
        """Running migration twice should not fail or duplicate data."""
        assert migrate_database(legacy_db)
        assert migrate_database(legacy_db)

        assert _table_exists(legacy_db, "relevant_articles")
        assert _count_rows(legacy_db, "relevant_articles") == 2
        assert not _table_exists(legacy_db, "cleaned_articles")

    def test_migration_handles_missing_table(self, tmp_path):
        """Migration should handle DB without cleaned_articles gracefully."""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(db_path)
        conn.commit()
        conn.close()

        assert migrate_database(str(db_path))
        assert not _table_exists(str(db_path), "cleaned_articles")
        # relevant_articles may or may not be created depending on migration path; just ensure no failure

