import asyncio
import pytest
from contextlib import asynccontextmanager

from src.news_scraper import NewsArticleScraper


class MockConfig:
    def get(self, key, default=None):
        values = {
            "NEWS_API_KEY": "api-key",
            "NEWS_API_URL": "http://example.com",
            "EVENT_REGISTRY_MENTIONS_URL": "http://example.com/mentions",
            "NEWS_API_REQUESTS_PER_SECOND": 1,
            "EVENT_REGISTRY_ARTICLES_COUNT": 50,
            "EVENT_REGISTRY_MENTIONS_COUNT": 100,
            "EVENT_REGISTRY_SOURCE_RANK_START": 0,
            "EVENT_REGISTRY_SOURCE_RANK_END": 50,
            "EVENT_REGISTRY_DUPLICATE_FILTER": "skipDuplicates",
            "EVENT_REGISTRY_MIN_BODY_LENGTH": 600,
            "EVENT_REGISTRY_ENABLE_URL_FALLBACK": False,
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
        self.last_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def post(self, *args, **kwargs):
        self.last_json = kwargs.get("json")
        @asynccontextmanager
        async def cm():
            yield self.response
        return cm()


@pytest.fixture
def scraper():
    return NewsArticleScraper(MockConfig())


def test_make_api_request_success(monkeypatch, scraper):
    response = FakeResponse(200, {"articles": {"results": [{"title": "A"}]}})

    def client_session(*args, **kwargs):
        return FakeSession(response)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    articles = asyncio.run(scraper._make_api_request({}))
    assert articles == [{"title": "A"}]


def test_make_api_request_rate_limit(monkeypatch, scraper):
    response = FakeResponse(429)

    def client_session(*args, **kwargs):
        return FakeSession(response)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    articles = asyncio.run(scraper._make_api_request({}))
    assert articles == []
    assert scraper.rate_limited


def test_fetch_for_term_flattens_category_payload(monkeypatch, scraper):
    response = FakeResponse(200, {"articles": {"results": [{"title": "B"}]}})
    sessions = []

    def client_session(*args, **kwargs):
        session = FakeSession(response)
        sessions.append(session)
        return session

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    results = asyncio.run(scraper._fetch_for_term("term"))
    assert results == [{"title": "B"}]
    assert "term" in sessions[0].last_json["keyword"]
    assert "-opinion" in sessions[0].last_json["keyword"]
    assert sessions[0].last_json["apiKey"] == "api-key"
    assert sessions[0].last_json["isDuplicateFilter"] == "skipDuplicates"


def test_build_search_query_includes_base_terms(scraper):
    query = scraper.build_search_query(["semaglutide", "tirzepatide"])
    assert "semaglutide" in query
    assert "tirzepatide" in query


def test_build_search_query_excludes_commentary(scraper):
    query = scraper.build_search_query(["pharma"])
    assert "-opinion" in query
    assert "-editorial" in query
    assert "-commentary" in query
    assert "-analysis" in query


def test_build_search_query_does_not_require_incident_keyword(scraper):
    """Query should not force an AND between base term and incident keywords."""
    query = scraper.build_search_query(["semaglutide"])
    assert "semaglutide" in query
    assert "+" not in query

