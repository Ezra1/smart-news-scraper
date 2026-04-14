import asyncio
import logging

import pytest
from contextlib import asynccontextmanager

from src.news_scraper import NewsArticleScraper, THENEWSAPI_MAX_PAGE_SIZE


class MockConfig:
    def get(self, key, default=None):
        values = {
            "NEWS_API_KEY": "api-key",
            "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
            "NEWS_API_REQUESTS_PER_SECOND": 1,
            "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
            "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
            "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
            "NEWS_API_PAGE_LIMIT": 50,
            "NEWS_API_LANGUAGE": "en",
            "NEWS_API_MIN_BODY_LENGTH": 600,
            "NEWS_API_ENABLE_URL_FALLBACK": False,
        }
        return values.get(key, default)


class FakeResponse:
    def __init__(self, status, json_data=None, text_data="", headers=None):
        self.status = status
        self._json = json_data or {}
        self._text = text_data
        self.headers = headers or {}

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
    response = FakeResponse(429, headers={"Retry-After": "2"})

    def client_session(*args, **kwargs):
        return FakeSession(response)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    articles = asyncio.run(scraper._make_api_request({}))
    assert articles == []
    assert scraper.rate_limited


def test_make_api_request_adapts_rps_from_rate_limit_headers(monkeypatch, scraper):
    response = FakeResponse(
        200,
        {"data": [{"title": "A"}]},
        headers={
            "X-RateLimit-Limit": "120",
            "X-RateLimit-Remaining": "30",
            "X-RateLimit-Reset": "30",
        },
    )

    def client_session(*args, **kwargs):
        return FakeSession(response)

    monkeypatch.setattr("aiohttp.ClientSession", client_session)

    articles = asyncio.run(scraper._make_api_request({}))
    assert articles == [{"title": "A"}]
    # 120/min with 90% headroom -> 1.8 RPS, bounded by config.
    assert scraper.rate_limiter.requests_per_second == pytest.approx(1.0)


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


def test_build_articles_payload_sets_language_from_query_spec(scraper):
    payload = scraper._build_articles_payload(
        "x",
        1,
        {},
        query_spec={"language": "de"},
    )
    assert payload["language"] == "de"
    assert "locale" not in payload


def test_build_search_query_for_single_term(scraper):
    query = scraper._build_search_query("semaglutide")
    assert query == "semaglutide"


def test_build_search_query_preserves_operator_syntax(scraper):
    query = scraper._build_search_query("smuggled + [medicine | tablets]")
    assert query == "smuggled + (medicine | tablets)"


def test_build_search_query_normalizes_whitespace(scraper):
    query = scraper._build_search_query('  "counterfeit medicine"   +   raid   ')
    assert query == '"counterfeit medicine" + raid'


class HighNewsPageLimitConfig(MockConfig):
    def get(self, key, default=None):
        if key == "NEWS_API_PAGE_LIMIT":
            return 100
        return super().get(key, default)


def test_news_api_page_limit_clamped_in_payload():
    """Configured limit above API max is clamped; payload uses effective limit."""
    s = NewsArticleScraper(HighNewsPageLimitConfig())
    assert s.configured_news_api_page_limit == 100
    assert s.articles_count == THENEWSAPI_MAX_PAGE_SIZE
    payload = s._build_articles_payload("term", 1, {})
    assert payload["limit"] == THENEWSAPI_MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_short_nonempty_page_continues_to_page_two(caplog, monkeypatch):
    """Short first page (< limit) must not end pagination when streak stop is disabled (default)."""
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 50,
                "FETCH_MAX_PAGES_PER_QUERY": 5,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 5,
                "FETCH_MAX_ARTICLES_PER_QUERY": 500,
                "FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP": 0,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())
    pages_called: list[int] = []

    async def fake_make(payload):
        pages_called.append(int(payload["page"]))
        p = int(payload["page"])
        if p == 1:
            return [{"url": f"https://example.com/p1-{i}"} for i in range(10)]
        return []

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)

    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 10
    assert pages_called == [1, 2]
    assert "Request page=2/" in caplog.text
    assert "empty_page" in caplog.text
    assert "final_stop_reason='empty_page'" in caplog.text


@pytest.mark.asyncio
async def test_short_page_clamped_limit_still_continues_pagination(caplog, monkeypatch):
    """NEWS_API_PAGE_LIMIT above API max clamps effective limit; short page still probes page 2."""
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 100,
                "FETCH_MAX_PAGES_PER_QUERY": 5,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 5,
                "FETCH_MAX_ARTICLES_PER_QUERY": 500,
                "FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP": 0,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())
    pages_called: list[int] = []

    async def fake_make(payload):
        assert payload["limit"] == THENEWSAPI_MAX_PAGE_SIZE
        pages_called.append(int(payload["page"]))
        p = int(payload["page"])
        if p == 1:
            return [{"url": f"https://example.com/p1-{i}"} for i in range(40)]
        return []

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)

    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 40
    assert pages_called == [1, 2]
    assert "effective_limit=50" in caplog.text
    assert "Request page=2/" in caplog.text
    assert "final_stop_reason='empty_page'" in caplog.text


@pytest.mark.asyncio
async def test_short_page_streak_stop_when_configured(caplog, monkeypatch):
    """FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP=N stops after N consecutive short non-empty pages."""
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 50,
                "FETCH_MAX_PAGES_PER_QUERY": 10,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 10,
                "FETCH_MAX_ARTICLES_PER_QUERY": 500,
                "FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP": 2,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())
    pages_called: list[int] = []

    async def fake_make(payload):
        pages_called.append(int(payload["page"]))
        p = int(payload["page"])
        if p <= 2:
            return [{"url": f"https://ex.test/p{p}-{i}"} for i in range(10)]
        return [{"url": f"https://ex.test/p{p}-{i}"} for i in range(50)]

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)

    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 20
    assert pages_called == [1, 2]
    assert "short_page_streak" in caplog.text
    assert "final_stop_reason='short_page_streak'" in caplog.text


@pytest.mark.asyncio
async def test_legacy_immediate_short_streak_one_matches_old_partial_stop(caplog, monkeypatch):
    """FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP=1 restores stop-after-first-short-page behavior."""
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 50,
                "FETCH_MAX_PAGES_PER_QUERY": 5,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 5,
                "FETCH_MAX_ARTICLES_PER_QUERY": 500,
                "FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP": 1,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())
    pages_called: list[int] = []

    async def fake_make(payload):
        pages_called.append(int(payload["page"]))
        return [{"url": f"https://example.com/p1-{i}"} for i in range(10)]

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)

    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 10
    assert pages_called == [1]
    assert "final_stop_reason='short_page_streak'" in caplog.text


@pytest.mark.asyncio
async def test_per_query_cap_stops_pagination(caplog, monkeypatch):
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 50,
                "FETCH_MAX_PAGES_PER_QUERY": 5,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 5,
                "FETCH_MAX_ARTICLES_PER_QUERY": 12,
                "FETCH_CONSECUTIVE_SHORT_PAGES_TO_STOP": 0,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())

    async def fake_make(payload):
        p = int(payload["page"])
        return [{"url": f"https://cap.test/{p}-{i}"} for i in range(50)]

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)

    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 12
    assert "per_query_cap_reached" in caplog.text
    assert "final_stop_reason='per_query_cap_reached'" in caplog.text


@pytest.mark.asyncio
async def test_fetch_articles_pages_max_pages_reached_logs_stop_reason(caplog, monkeypatch):
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 3,
                "FETCH_MAX_PAGES_PER_QUERY": 2,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 2,
                "FETCH_MAX_ARTICLES_PER_QUERY": 100,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())

    async def fake_make(payload):
        p = payload["page"]
        return [{"url": f"https://ex.test/{p}_{i}"} for i in range(3)]

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)

    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 6
    assert "max_pages_reached" in caplog.text
    assert "final_stop_reason='max_pages_reached'" in caplog.text


def test_pagination_identity_key_url_vs_fallback(scraper):
    k1 = scraper._pagination_identity_key({"url": "HTTPS://Ex.COM/A", "title": "T"})
    k2 = scraper._pagination_identity_key({"url": "https://ex.com/a", "title": "Other"})
    assert k1 == k2
    k3 = scraper._pagination_identity_key({"title": "Hello", "source": {"name": "SRC"}})
    k4 = scraper._pagination_identity_key({"title": "hello", "source": {"name": "src"}})
    assert k3 == k4


@pytest.mark.asyncio
async def test_fetch_articles_pages_stops_on_duplicate_only_page(caplog, monkeypatch):
    class MC:
        def get(self, key, default=None):
            base = {
                "NEWS_API_KEY": "k",
                "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
                "NEWS_API_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MAX_REQUESTS_PER_SECOND": 10,
                "NEWS_API_MIN_REQUESTS_PER_SECOND": 0.2,
                "NEWS_API_RATE_LIMIT_HEADROOM": 0.9,
                "NEWS_API_PAGE_LIMIT": 10,
                "FETCH_MAX_PAGES_PER_QUERY": 5,
                "FETCH_MAX_PAGES_PER_QUERY_HIGH_RECALL": 5,
                "FETCH_MAX_ARTICLES_PER_QUERY": 100,
                "HIGH_RECALL_MODE": False,
                "NEWS_API_LANGUAGE": "en",
                "NEWS_API_MIN_BODY_LENGTH": 600,
                "NEWS_API_ENABLE_URL_FALLBACK": False,
            }
            return base.get(key, default)

    s = NewsArticleScraper(MC())
    pages_called = []

    async def fake_make(payload):
        pages_called.append(payload["page"])
        p = payload["page"]
        row = {"url": "https://dup.example/a", "title": "A"}
        if p == 1:
            return [dict(row) for _ in range(10)]
        return [dict(row) for _ in range(10)]

    async def noop_wait():
        return None

    monkeypatch.setattr(s, "_make_api_request", fake_make)
    monkeypatch.setattr(s, "_wait_for_rate_limit", noop_wait)
    with caplog.at_level(logging.INFO):
        out = await s._fetch_articles_pages("q", {}, None)
    assert len(out) == 1
    assert pages_called == [1, 2]
    assert "duplicate_only_page" in caplog.text
    assert "final_stop_reason='duplicate_only_page'" in caplog.text


def test_fetch_for_term_retries_with_fallback_date_window(monkeypatch, scraper):
    calls = []

    async def fake_fetch_articles_pages(term, date_filters, query_spec=None):
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

