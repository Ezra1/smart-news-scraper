"""Integration-ish tests for the CLI workflow with heavy mocking to avoid I/O and network."""

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main as cli
from src.openai_relevance_processing import ProcessingResult


def _make_inputs(*values):
    """Helper to feed a sequence of inputs to builtins.input."""
    vals = list(values)

    def _input(_prompt=""):
        return vals.pop(0)

    return _input


@pytest.fixture(autouse=True)
def ensure_data_dir():
    Path("data").mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def temp_db_inside_data(tmp_path):
    db_path = tmp_path / "data" / "temp.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch()
    return db_path


@pytest.fixture
def temp_search_terms_inside_data(tmp_path):
    terms_path = tmp_path / "data" / "terms.txt"
    terms_path.parent.mkdir(parents=True, exist_ok=True)
    terms_path.write_text("alpha\nbeta\n", encoding="utf-8")
    return terms_path


class DummyDB:
    def __init__(self, path):
        self.path = path
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params))
        return []

    def close(self):
        return None


def _patch_pipeline(monkeypatch, db_instance, search_terms=None, processor_results=None):
    """Patch pipeline collaborators to avoid network/DB/file I/O."""
    search_terms = search_terms if search_terms is not None else [{"id": 1, "term": "alpha"}]
    processor_results = processor_results if processor_results is not None else [
        ProcessingResult(article={"id": 1, "title": "t", "content": "c", "url": "u"}, status="relevant")
    ]

    # DatabaseManager returns our dummy
    db_ctor = MagicMock(return_value=db_instance)
    monkeypatch.setattr(cli, "DatabaseManager", db_ctor)

    # SearchTermManager mock
    stm = MagicMock()
    stm.get_search_terms.return_value = search_terms
    stm.insert_search_terms_from_txt.return_value = None
    stm_cls = MagicMock(return_value=stm)
    monkeypatch.setattr(cli, "SearchTermManager", stm_cls)

    # ArticleManager mock
    am = MagicMock()
    am.get_articles.return_value = [{"id": 1, "title": "t", "content": "c", "url": "u"}]
    am.insert_article.return_value = 1
    am_cls = MagicMock(return_value=am)
    monkeypatch.setattr(cli, "ArticleManager", am_cls)

    # Scraper mock
    scraper = MagicMock()
    scraper.rate_limited = False
    scraper.fetch_all_articles.return_value = [{"id": 1, "title": "t", "content": "c", "url": "u"}]
    scraper_cls = MagicMock(return_value=scraper)
    monkeypatch.setattr(cli, "NewsArticleScraper", scraper_cls)

    # Processor mock
    processor = MagicMock()
    processor.process_articles.return_value = processor_results
    processor_cls = MagicMock(return_value=processor)
    monkeypatch.setattr(cli, "ArticleProcessor", processor_cls)

    # RelevanceFilter mock
    rf = MagicMock()
    rf.process_latest_results.return_value = None
    rf.analyze_results.return_value = None
    rf_cls = MagicMock(return_value=rf)
    monkeypatch.setattr(cli, "RelevanceFilter", rf_cls)

    # Extractor mock
    extract_mock = MagicMock()
    monkeypatch.setattr(cli, "extract_cleaned_data", extract_mock)

    return SimpleNamespace(
        db_ctor=db_ctor,
        search_term_manager=stm,
        article_manager=am,
        scraper=scraper,
        processor=processor,
        relevance_filter=rf,
        extract_mock=extract_mock,
    )


class TestCLIWorkflow:
    def test_cli_uses_specified_db_path(self, monkeypatch, temp_db_inside_data, temp_search_terms_inside_data):
        """CLI should honor the user-specified DB path."""
        db_instance = DummyDB(str(temp_db_inside_data))
        patches = _patch_pipeline(monkeypatch, db_instance)

        inputs = _make_inputs(
            str(temp_db_inside_data),
            str(temp_search_terms_inside_data),
            "n",
            "n",
        )
        monkeypatch.setattr("builtins.input", inputs)

        asyncio.run(cli.main())

        patches.db_ctor.assert_called_with(str(temp_db_inside_data))
        # Ensure default path was never used
        default_path = Path("data/news_articles.db").resolve()
        assert patches.db_ctor.call_args[0][0] != str(default_path)

    def test_cli_fetch_and_process_flow(self, monkeypatch, temp_db_inside_data, temp_search_terms_inside_data):
        """Happy-path: fetch, process, and export get invoked."""
        db_instance = DummyDB(str(temp_db_inside_data))
        patches = _patch_pipeline(monkeypatch, db_instance)

        inputs = _make_inputs(
            str(temp_db_inside_data),
            str(temp_search_terms_inside_data),
            "n",
            "n",
        )
        monkeypatch.setattr("builtins.input", inputs)

        asyncio.run(cli.main())

        patches.scraper.fetch_all_articles.assert_called()
        patches.processor.process_articles.assert_called()
        patches.extract_mock.assert_called()
        patches.relevance_filter.process_latest_results.assert_called()

    def test_cli_handles_empty_search_terms(self, monkeypatch, temp_db_inside_data, temp_search_terms_inside_data):
        """CLI should exit gracefully when no search terms are present."""
        db_instance = DummyDB(str(temp_db_inside_data))
        patches = _patch_pipeline(monkeypatch, db_instance, search_terms=[])

        inputs = _make_inputs(
            str(temp_db_inside_data),
            str(temp_search_terms_inside_data),
            "n",
            "n",
        )
        monkeypatch.setattr("builtins.input", inputs)

        asyncio.run(cli.main())

        # When no terms, fetch should not be called
        patches.scraper.fetch_all_articles.assert_not_called()

