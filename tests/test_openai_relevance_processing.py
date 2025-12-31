import asyncio
import pytest

from src.openai_relevance_processing import ArticleProcessor


class DummyRateLimiter:
    def wait_if_needed(self):
        return None


class DummyDBManager:
    def execute_query(self, query, params):
        return []


class DummyArticleManager:
    def __init__(self):
        self.insert_calls = []

    def insert_relevant_article(self, **kwargs):
        self.insert_calls.append(kwargs)


class FakeParsed:
    def __init__(self, score):
        self.relevance_score = score


class FakeMessage:
    def __init__(self, score):
        self.parsed = FakeParsed(score)


class FakeChoice:
    def __init__(self, score):
        self.message = FakeMessage(score)


class FakeResponse:
    def __init__(self, score):
        self.choices = [FakeChoice(score)]


class FakeCompletions:
    def __init__(self, score):
        self.score = score

    def parse(self, *args, **kwargs):
        return FakeResponse(self.score)


class FakeChat:
    def __init__(self, score):
        self.completions = FakeCompletions(score)


class FakeBeta:
    def __init__(self, score):
        self.chat = FakeChat(score)


class FakeClient:
    def __init__(self, score):
        self.beta = FakeBeta(score)


def make_processor(score: float, threshold: float = 0.5) -> ArticleProcessor:
    processor = ArticleProcessor.__new__(ArticleProcessor)
    processor.RELEVANCE_THRESHOLD = threshold
    processor.client = FakeClient(score)
    processor.rate_limiter = DummyRateLimiter()
    processor.semaphore = asyncio.Semaphore(1)
    processor.article_manager = DummyArticleManager()
    processor.db_manager = DummyDBManager()
    processor.relevant = 0
    processor.irrelevant = 0
    processor.total_relevant = 0
    processor.max_relevance_score = 0.0
    processor.context_message = {"role": "system", "content": "test"}
    return processor


@pytest.mark.asyncio
async def test_process_article_returns_article_with_score_when_relevant():
    processor = make_processor(score=0.9, threshold=0.5)
    article = {"id": 1, "title": "t", "content": "c", "url": "https://example.com"}

    result = await processor.process_article(article, remaining=1)

    assert result is not None
    assert result["relevance_score"] == 0.9
    assert processor.article_manager.insert_calls[0]["relevance_score"] == 0.9


@pytest.mark.asyncio
async def test_process_article_returns_none_when_irrelevant():
    processor = make_processor(score=0.1, threshold=0.5)
    article = {"id": 2, "title": "t", "content": "c", "url": "https://example.com"}

    result = await processor.process_article(article, remaining=1)

    assert result is None
    assert processor.article_manager.insert_calls == []

