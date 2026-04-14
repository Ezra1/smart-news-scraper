import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from src.openai_relevance_processing import ArticleProcessor


@pytest.fixture
def sample_article():
    return {
        "id": 123,
        "title": "Sample",
        "content": "Body",
        "url": "https://example.com/article",
        "source": {"name": "Example"},
        "url_to_image": "",
        "published_at": "2024-01-01",
    }


@pytest.fixture
def fake_client():
    def _make(score: float) -> Mock:
        parsed = Mock(relevance_score=score)
        message = Mock(parsed=parsed)
        choice = Mock(message=message)
        response = Mock(choices=[choice])

        parse = Mock(return_value=response)
        completions = Mock(parse=parse)
        chat = Mock(completions=completions)
        beta = Mock(chat=chat)

        client = Mock(beta=beta)
        return client

    return _make


@pytest.fixture
def processor_factory(fake_client):
    def _make(score: float, threshold: float = 0.7) -> ArticleProcessor:
        processor = ArticleProcessor.__new__(ArticleProcessor)
        processor.RELEVANCE_THRESHOLD = threshold
        processor.client = fake_client(score)
        processor.rate_limiter = Mock(
            wait_if_needed=Mock(),
            wait_if_needed_async=AsyncMock(return_value=None),
        )
        processor.semaphore = asyncio.Semaphore(1)
        processor.article_manager = Mock()
        processor.article_manager.insert_relevant_article = Mock()
        processor.article_manager.api_fields_from_article = Mock(return_value={})
        processor.db_manager = Mock()
        processor.db_manager.execute_query = Mock(return_value=[])
        processor.relevant = 0
        processor.irrelevant = 0
        processor.total_relevant = 0
        processor.max_relevance_score = 0.0
        processor.error_count = 0
        processor.context_message = {"role": "system", "content": "test context"}
        processor.enable_llm_guardrail = False
        processor.cancelled = False
        return processor

    return _make


class TestArticleProcessorRelevance:
    """Regression tests for relevance score propagation."""

    @pytest.mark.asyncio
    async def test_relevant_article_returned_with_score(self, processor_factory, sample_article):
        """Regression: relevance_score must be set before threshold gating."""
        processor = processor_factory(score=0.85, threshold=0.7)
        article = sample_article.copy()

        result = await processor.process_article(article, remaining=1)

        assert result is not None
        assert result.status == "relevant"
        assert result.article["relevance_score"] == pytest.approx(0.85)
        processor.article_manager.insert_relevant_article.assert_called_once()
        assert (
            processor.article_manager.insert_relevant_article.call_args.kwargs["relevance_score"]
            == pytest.approx(0.85)
        )

    @pytest.mark.asyncio
    async def test_irrelevant_article_filtered_out(self, processor_factory, sample_article):
        """Regression: low-score articles should be filtered even when score set."""
        processor = processor_factory(score=0.2, threshold=0.7)
        article = sample_article.copy()

        result = await processor.process_article(article, remaining=1)

        assert result is not None
        assert result.status == "irrelevant"
        assert article["relevance_score"] == pytest.approx(0.2)
        processor.article_manager.insert_relevant_article.assert_not_called()

    @pytest.mark.asyncio
    async def test_edge_case_at_threshold(self, processor_factory, sample_article):
        """Regression: boundary score equal to threshold treated as relevant."""
        processor = processor_factory(score=0.7, threshold=0.7)
        article = sample_article.copy()

        result = await processor.process_article(article, remaining=1)

        assert result is not None
        assert result.status == "relevant"
        assert result.article["relevance_score"] == pytest.approx(0.7)
        processor.article_manager.insert_relevant_article.assert_called_once()

    @pytest.mark.asyncio
    async def test_relevance_score_persists_to_db(self, processor_factory, sample_article):
        """Regression: ensure DB insert receives computed relevance_score."""
        processor = processor_factory(score=0.92, threshold=0.7)
        article = sample_article.copy()

        await processor.process_article(article, remaining=1)

        processor.article_manager.insert_relevant_article.assert_called_once()
        insert_kwargs = processor.article_manager.insert_relevant_article.call_args.kwargs
        assert insert_kwargs["raw_article_id"] == sample_article["id"]
        assert insert_kwargs["relevance_score"] == pytest.approx(0.92)

