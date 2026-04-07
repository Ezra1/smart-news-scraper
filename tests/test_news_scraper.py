import asyncio
import pytest
from contextlib import asynccontextmanager

from src.news_scraper import NewsArticleScraper


class MockConfig:
    def get(self, key, default=None):
        values = {
            "NEWS_API_KEY": "api-key",
            "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
            "NEWS_API_REQUESTS_PER_SECOND": 1,
            "NEWS_API_PAGE_LIMIT": 50,
            "NEWS_API_LANGUAGE": "en",
            "NEWS_API_MIN_BODY_LENGTH": 600,
            "NEWS_API_ENABLE_URL_FALLBACK": False,
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
        self.last_params = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def get(self, *args, **kwargs):
        self.last_params = kwargs.get("params")
        @asynccontextmanager
        async def cm():
            yield self.response
        return cm()


@pytest.fixture
def scraper():
    return NewsArticleScraper(MockConfig())


def test_make_api_request_success(monkeypatch, scraper):
    response = FakeResponse(200, {"data": [{"title": "A"}]})

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
    response = FakeResponse(200, {"data": [{"title": "B"}]})
    sessions = []

    def client_session(*args, **kwargs):
        session = FakeSession(response)
        sessions.append(session)
        return session

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    results = asyncio.run(scraper._fetch_for_term("term"))
    assert results == [{"title": "B"}]
    assert sessions[0].last_params["search"] == "term"
    assert sessions[0].last_params["api_token"] == "api-key"
    assert sessions[0].last_params["language"] == "en"


def test_build_search_query_for_single_term(scraper):
    query = scraper._build_search_query("semaglutide")
    assert query == "semaglutide"


def test_build_search_query_preserves_operator_syntax(scraper):
    query = scraper._build_search_query("smuggled + [medicine | tablets]")
    assert query == "smuggled + (medicine | tablets)"


def test_build_search_query_normalizes_whitespace(scraper):
    query = scraper._build_search_query('  "counterfeit medicine"   +   raid   ')
    assert query == '"counterfeit medicine" + raid'


def test_fetch_for_term_retries_with_fallback_date_window(monkeypatch, scraper):
    calls = []

    async def fake_fetch_articles_pages(term, date_filters):
        calls.append((term, date_filters))
        # Simulate the original failure mode: zero results with explicit dates.
        if date_filters == {"published_after": "2024-11-03", "published_before": "2026-01-05"}:
            return []
        # Simulate success when retrying with fallback/default window.
        return [{"title": "Recovered from fallback"}]

    monkeypatch.setattr(scraper, "_fetch_articles_pages", fake_fetch_articles_pages)

    results = asyncio.run(
        scraper._fetch_for_term(
            "seized + medicine",
            date_params={"published_after": "2024-11-03", "published_before": "2026-01-05"},
        )
    )

    assert len(results) == 1
    assert results[0]["title"] == "Recovered from fallback"
    assert results[0]["_retrieved_via_fallback_window"] is True
    assert len(calls) == 2
    assert calls[0][1] == {"published_after": "2024-11-03", "published_before": "2026-01-05"}
    # Second call should use the internal default/fallback date window.
    assert "published_after" in calls[1][1]
    assert "published_before" in calls[1][1]
    assert calls[1][1] != calls[0][1]

