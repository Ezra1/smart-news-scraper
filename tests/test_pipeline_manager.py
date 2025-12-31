"""Tests for PipelineManager callback handling."""
import pytest
from unittest.mock import Mock, MagicMock

from src.pipeline_manager import PipelineManager


class DummyDBManager:
    def execute_query(self, query, params):
        return []


class DummyConfigManager:
    def get(self, key, default=None):
        return default

    def validate(self):
        return True


class DummyScraper:
    def __init__(self, articles):
        self.articles = articles
        self.rate_limited = False

    async def fetch_articles(self, terms, term_map):
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

    @pytest.mark.asyncio
    async def test_fetch_articles_without_callbacks(self):
        """fetch_articles should work without GUI callbacks."""
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1, "title": "ok"}]),
            validator=DummyValidator(),
        )

        result = await manager.fetch_articles(["test-term"])

        assert result == [{"id": 1, "title": "ok"}]

    @pytest.mark.asyncio
    async def test_status_callback_called_when_provided(self):
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

        await manager.fetch_articles(["term"])

        status_cb.assert_any_call("Starting article fetch...", False, False, False)
        progress_cb.assert_any_call(1, 1)

    @pytest.mark.asyncio
    async def test_progress_callback_called_when_provided(self):
        """Verify progress callbacks work when provided."""
        progress_cb = MagicMock()
        manager = PipelineManager(
            db_manager=DummyDBManager(),
            config_manager=DummyConfigManager(),
            scraper=DummyScraper([{"id": 1}]),
            validator=DummyValidator(),
        )
        manager.set_callbacks(progress_cb, MagicMock())

        await manager.fetch_articles(["only-term"])

        progress_cb.assert_called_with(1, 1)

    @pytest.mark.asyncio
    async def test_mixed_callbacks_some_provided(self):
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

        result = await manager.fetch_articles(["term"])

        assert result == [{"id": 2}]
        status_cb.assert_any_call("Starting article fetch...", False, False, False)

