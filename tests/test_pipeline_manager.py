"""Tests for PipelineManager callback handling."""
import asyncio
import pytest
from unittest.mock import Mock, MagicMock, call

from src.pipeline_manager import PipelineManager


class DummyDBManager:
    def execute_query(self, query, params):
        return []


class DummyConfigManager:
    def get(self, key, default=None):
        values = {
            "QUERY_EXPANSION_ENABLED": False,
            "QUERY_EXPANSION_USE_AI": False,
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 3,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 120,
            "QUERY_EXPANSION_LANGUAGES": "en",
            "MAXIMUM_RECALL_MODE": False,
            "HIGH_RECALL_MODE": True,
            "REQUEST_BUDGET_MODE": "aggressive",
            "REQUEST_BUDGET_PER_RUN": 100,
            "RELEVANCE_THRESHOLD": 0.7,
        }
        return values.get(key, default)

    def get_context_message(self):
        return {"role": "system", "content": "test"}

    def validate(self):
        return True


class DummyScraper:
    def __init__(self, articles):
        self.articles = articles
        self.rate_limited = False

    async def fetch_articles(self, terms, term_map, date_params=None):
        return self.articles


class DummyValidator:
    def clean_article(self, article):
        return article


class TestPipelineManagerCallbacks:
    """Regression tests for callback safety."""

    def test_instantiate_without_callbacks(self):
        """PipelineManager should instantiate without any callbacks set."""
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([]),
            validator=DummyValidator(),
        )

        # Should not raise when invoking default no-op callbacks
        manager.progress_callback(0, 0)
        manager.status_callback("ok", False, False, False)

        assert manager.scraper is not None
        assert manager.validator is not None

    def test_fetch_articles_without_callbacks(self):
        """fetch_articles should work without GUI callbacks."""
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1, "title": "ok"}]),
            validator=DummyValidator(),
        )

        result = asyncio.run(manager.fetch_articles(["test-term"]))

        assert result == [{"id": 1, "title": "ok"}]

    def test_status_callback_called_when_provided(self):
        """Verify callbacks ARE called when explicitly provided."""
        status_cb = MagicMock()
        progress_cb = MagicMock()
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1, "title": "ok"}]),
            validator=DummyValidator(),
        )
        manager.set_callbacks(progress_cb, status_cb)

        asyncio.run(manager.fetch_articles(["term"]))

        status_cb.assert_has_calls(
            [
                call("Starting article fetch...", False, False, False),
                call("Processing term 1/1: term [lang=default] (0 articles found)", False, False, False),
                call("Completed fetch: 1 articles from 1/1 terms", False, False, True),
            ],
            any_order=False,
        )
        progress_cb.assert_called_once_with(1, 1)

    def test_progress_callback_called_when_provided(self):
        """Verify progress callbacks work when provided."""
        progress_cb = MagicMock()
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1}]),
            validator=DummyValidator(),
        )
        manager.set_callbacks(progress_cb, MagicMock())

        asyncio.run(manager.fetch_articles(["only-term"]))

        progress_cb.assert_called_with(1, 1)

    def test_mixed_callbacks_some_provided(self):
        """Only status_callback provided, progress left as default."""
        status_cb = MagicMock()
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 2}]),
            validator=DummyValidator(),
        )
        # Provide only status callback; progress remains default no-op
        manager.set_callbacks(None, status_cb)

        result = asyncio.run(manager.fetch_articles(["term"]))

        assert result == [{"id": 2}]
        status_cb.assert_has_calls(
            [
                call("Starting article fetch...", False, False, False),
                call("Processing term 1/1: term [lang=default] (0 articles found)", False, False, False),
                call("Completed fetch: 1 articles from 1/1 terms", False, False, True),
            ],
            any_order=False,
        )

    def test_filter_candidates_invokes_funnel_and_returns_filtered(self):
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([]),
            validator=DummyValidator(),
        )
        manager.candidate_filter = MagicMock()
        manager.candidate_filter.filter_candidates.return_value = (
            [{"id": 1, "title": "kept"}],
            {
                "retrieved_count": 3,
                "after_heuristics_count": 2,
                "after_semantic_count": 1,
                "sent_to_llm_count": 1,
                "dropped_by_reason": {"no_overlap": 2},
            },
        )

        result = manager.filter_candidates(
            [{"id": 1}, {"id": 2}, {"id": 3}],
            query_terms_by_id={1: "seized medicine"},
        )

        assert result == [{"id": 1, "title": "kept"}]
        manager.candidate_filter.filter_candidates.assert_called_once_with(
            [{"id": 1}, {"id": 2}, {"id": 3}],
            query_terms_by_id={1: "seized medicine"},
        )

    def test_dedupe_articles_by_url_preserves_order(self):
        rows = [
            {"id": 1, "url": "https://example.com/News"},
            {"id": 2, "url": "https://example.com/news"},
            {"id": 3, "url": ""},
            {"id": 4, "title": "no-url"},
        ]
        out = PipelineManager._dedupe_articles_by_url(rows)
        assert [a["id"] for a in out] == [1, 3, 4]

    def test_fetch_articles_empty_terms_short_circuits(self):
        status_cb = MagicMock()
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1, "title": "ok"}]),
            validator=DummyValidator(),
        )
        manager.set_callbacks(MagicMock(), status_cb)

        result = asyncio.run(manager.fetch_articles([]))

        assert result == []
        status_cb.assert_has_calls(
            [
                call("Starting article fetch...", False, False, False),
                call("Completed fetch: 0 articles from 0/0 terms", False, False, True),
            ],
            any_order=False,
        )

    def test_fetch_metrics_include_expansion_diagnostics(self):
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1, "url": "https://example.com/a", "root_term": "term"}]),
            validator=DummyValidator(),
        )

        result = asyncio.run(manager.fetch_articles(["term"]))

        assert result
        assert manager._last_fetch_meta["expansion_diagnostics"]["ai_attempts"] == 0
        assert manager._last_fetch_meta["top_roots_by_fetch_count"] == [{"term": "term", "count": 1}]

    def test_execute_pipeline_emits_funnel_rates_and_top_relevant_roots(self):
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1, "url": "https://example.com/a", "root_term": "counterfeit medicine"}]),
            validator=DummyValidator(),
        )
        manager.filter_candidates = Mock(
            return_value=[{"id": 1, "url": "https://example.com/a", "root_term": "counterfeit medicine"}]
        )
        manager.processor = type("DummyProcessor", (), {"RELEVANCE_THRESHOLD": 0.0})()

        async def fake_analyze(_):
            return type(
                "Analysis",
                (),
                {
                    "relevant_articles": [{"id": 1, "root_term": "counterfeit medicine"}],
                    "analyzed_count": 1,
                    "error_count": 0,
                },
            )()

        manager.analyze_articles = fake_analyze

        run_result = asyncio.run(manager.execute_pipeline([{"id": 10, "term": "counterfeit medicine"}]))

        assert run_result.run_metrics["funnel_rates"]["fetch_to_relevant"] == 1.0
        assert run_result.run_metrics["top_roots_by_relevant_count"] == [
            {"term": "counterfeit medicine", "count": 1}
        ]

