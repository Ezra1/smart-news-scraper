import pytest
from contextlib import asynccontextmanager

from src.news_scraper import NewsArticleScraper


class MockConfig:
    def get(self, key, default=None):
        values = {
            "NEWS_API_KEY": "api-key",
            "NEWS_API_URL": "http://example.com",
            "NEWS_API_REQUESTS_PER_SECOND": 1,
        }
        return values.get(key, default)


class FakeResponse:
    def __init__(self, status, json_data=None, text_data=""):
        self.status = status
        self._json = json_data or {}
        self._text = text_data

    async def json(self):
        return self._json

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def get(self, *args, **kwargs):
        @asynccontextmanager
        async def cm():
            yield self.response
        return cm()


@pytest.fixture
def scraper():
    return NewsArticleScraper(MockConfig())


@pytest.mark.asyncio
async def test_make_api_request_success(monkeypatch, scraper):
    response = FakeResponse(200, {"articles": [{"title": "A"}]})

    def client_session(*args, **kwargs):
        return FakeSession(response)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    articles = await scraper._make_api_request({})
    assert articles == [{"title": "A"}]


@pytest.mark.asyncio
async def test_make_api_request_rate_limit(monkeypatch, scraper):
    response = FakeResponse(429)

    def client_session(*args, **kwargs):
        return FakeSession(response)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    articles = await scraper._make_api_request({})
    assert articles == []
    assert scraper.rate_limited


@pytest.mark.asyncio
async def test_fetch_for_term_retry(monkeypatch, scraper):
    first = FakeResponse(200, {"articles": []})
    second = FakeResponse(200, {"articles": [{"title": "B"}]})
    responses = [first, second]

    def client_session(*args, **kwargs):
        resp = responses.pop(0)
        return FakeSession(resp)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    results = await scraper._fetch_for_term("term")
    assert results == [{"title": "B"}]

