from src.candidate_filter import CandidateFilter


class MockConfig:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def get(self, key, default=None):
        values = {
            "PRELLM_ENABLE_FILTERING": True,
            "PRELLM_MIN_CONTENT_CHARS": 20,
            "PRELLM_MAX_CONTENT_CHARS": 2000,
            "PRELLM_MIN_QUERY_TOKEN_OVERLAP": 1,
            "PRELLM_REQUIRE_INCIDENT_SIGNAL": False,
            "PRELLM_DEDUP_BY_URL": True,
            "PRELLM_DEDUP_BY_TITLE": True,
            "PRELLM_TOP_K_PER_TERM": 5,
            "PRELLM_STAGE3_ENABLED": False,
            "PRELLM_LOG_DROPS": False,
            "NEWS_SOURCE_ALLOWLIST": "",
            "NEWS_SOURCE_BLOCKLIST": "",
        }
        values.update(self.overrides)
        return values.get(key, default)


class DummyDBManager:
    def execute_query(self, query, params=None):
        return []


class RecordingArticleManager:
    def __init__(self):
        self.records = []

    def record_pre_llm_filter_result(
        self,
        raw_article_id,
        decision,
        reason,
        heuristic_score=0.0,
        lexical_overlap=0,
        metadata=None,
    ):
        self.records.append(
            {
                "raw_article_id": raw_article_id,
                "decision": decision,
                "reason": reason,
                "heuristic_score": heuristic_score,
                "lexical_overlap": lexical_overlap,
                "metadata": metadata or {},
            }
        )
        return True


def _make_article(article_id, title, content, url, search_term_id=1):
    return {
        "id": article_id,
        "title": title,
        "content": content,
        "url": url,
        "search_term_id": search_term_id,
    }


def test_candidate_filter_keeps_high_overlap_article():
    manager = RecordingArticleManager()
    filterer = CandidateFilter(MockConfig(), db_manager=DummyDBManager(), article_manager=manager)
    articles = [
        _make_article(
            1,
            "Police seized counterfeit medicines",
            "Authorities seized counterfeit medicines in a warehouse raid.",
            "https://example.com/a1",
        )
    ]
    filtered, stats = filterer.filter_candidates(articles, query_terms_by_id={1: "seized medicine"})

    assert len(filtered) == 1
    assert filtered[0]["prellm_query_token_overlap"] >= 1
    assert stats["retrieved_count"] == 1
    assert stats["sent_to_llm_count"] == 1
    assert manager.records[0]["decision"] == "keep"


def test_candidate_filter_drops_duplicates_and_records_reason():
    manager = RecordingArticleManager()
    filterer = CandidateFilter(MockConfig(), db_manager=DummyDBManager(), article_manager=manager)
    articles = [
        _make_article(1, "Seized meds in port", "Police seized medicine at the port", "https://example.com/a1"),
        _make_article(2, "Seized meds in port", "Police seized medicine at the port", "https://example.com/a1"),
    ]
    filtered, stats = filterer.filter_candidates(articles, query_terms_by_id={1: "seized medicine"})

    assert len(filtered) == 1
    assert stats["dropped_by_reason"]["duplicate_url"] == 1
    assert any(r["reason"] == "duplicate_url" and r["decision"] == "drop" for r in manager.records)


def test_candidate_filter_enforces_top_k_per_term():
    manager = RecordingArticleManager()
    config = MockConfig({"PRELLM_TOP_K_PER_TERM": 1})
    filterer = CandidateFilter(config, db_manager=DummyDBManager(), article_manager=manager)
    articles = [
        _make_article(1, "seized medicine alpha", "seized medicine details", "https://example.com/a1"),
        _make_article(2, "seized medicine beta", "seized medicine details", "https://example.com/a2"),
    ]
    filtered, stats = filterer.filter_candidates(articles, query_terms_by_id={1: "seized medicine"})

    assert len(filtered) == 1
    assert stats["dropped_by_reason"]["top_k_trim"] == 1


def test_candidate_filter_uses_query_term_for_multilingual_overlap():
    manager = RecordingArticleManager()
    filterer = CandidateFilter(MockConfig(), db_manager=DummyDBManager(), article_manager=manager)
    articles = [
        {
            **_make_article(
                10,
                "La policia incauta medicamentos falsificados",
                "Autoridades incautaron medicamentos falsificados en una redada local.",
                "https://example.com/es-1",
            ),
            "query_term": "medicamentos falsificados",
            "query_language": "es",
        }
    ]
    filtered, stats = filterer.filter_candidates(articles, query_terms_by_id={1: "counterfeit medicine"})

    assert len(filtered) == 1
    assert stats["sent_to_llm_count"] == 1
    assert manager.records[0]["decision"] == "keep"
    assert filtered[0]["prellm_query_token_overlap"] >= 1
