from types import SimpleNamespace

import src.query_expander as query_expander
from src.query_expander import build_settings, expand_terms_to_queries


class DummyConfig:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def get(self, key, default=None):
        return self.overrides.get(key, default)


def test_expand_terms_with_fallback_and_caps():
    config = DummyConfig(
        {
            "QUERY_EXPANSION_ENABLED": True,
            "QUERY_EXPANSION_USE_AI": False,
            "QUERY_EXPANSION_LANGUAGES": "en,es",
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 2,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 3,
        }
    )
    settings = build_settings(config)
    expanded = expand_terms_to_queries(["counterfeit medicine"], settings)

    assert len(expanded) == 3
    assert expanded[0].root_term == "counterfeit medicine"
    assert expanded[0].language in {"en", "es"}


def test_high_recall_off_forces_english_only_languages():
    config = DummyConfig(
        {
            "HIGH_RECALL_MODE": False,
            "QUERY_EXPANSION_ENABLED": True,
            "QUERY_EXPANSION_USE_AI": False,
            "QUERY_EXPANSION_LANGUAGES": "en,es,fr",
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 2,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 20,
        }
    )
    settings = build_settings(config)
    assert settings.languages == ["en"]


def test_maximum_recall_mode_raises_expansion_floors():
    config = DummyConfig(
        {
            "MAXIMUM_RECALL_MODE": True,
            "HIGH_RECALL_MODE": True,
            "QUERY_EXPANSION_ENABLED": True,
            "QUERY_EXPANSION_USE_AI": False,
            "QUERY_EXPANSION_LANGUAGES": "en",
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 2,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 50,
        }
    )
    settings = build_settings(config)
    assert settings.variants_per_term >= 10
    assert settings.max_total_queries >= 800


def test_expand_terms_disabled_single_language():
    config = DummyConfig(
        {
            "QUERY_EXPANSION_ENABLED": False,
            "QUERY_EXPANSION_LANGUAGES": "en",
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 1,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 5,
        }
    )
    settings = build_settings(config)
    expanded = expand_terms_to_queries(["smuggled medicine"], settings)

    assert len(expanded) == 1
    assert expanded[0].term == "smuggled medicine"
    assert expanded[0].language == ""


def test_expand_terms_ai_parses_fenced_json(monkeypatch):
    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content='```json\n["alpha", "beta"]\n```'
                                )
                            )
                        ]
                    )

    monkeypatch.setattr(query_expander, "get_client", lambda: DummyClient())
    config = DummyConfig(
        {
            "QUERY_EXPANSION_ENABLED": True,
            "QUERY_EXPANSION_USE_AI": True,
            "QUERY_EXPANSION_LANGUAGES": "en",
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 2,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 5,
        }
    )
    settings = build_settings(config)
    diagnostics = {}
    expanded = expand_terms_to_queries(["counterfeit medicine"], settings, diagnostics=diagnostics)

    assert len(expanded) == 2
    assert [q.term for q in expanded] == ["alpha", "beta"]
    assert diagnostics["ai_attempts"] == 1
    assert diagnostics["ai_fallbacks"] == 0


def test_expand_terms_ai_falls_back_and_tracks_language(monkeypatch):
    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
                    )

    monkeypatch.setattr(query_expander, "get_client", lambda: DummyClient())
    config = DummyConfig(
        {
            "QUERY_EXPANSION_ENABLED": True,
            "QUERY_EXPANSION_USE_AI": True,
            "QUERY_EXPANSION_LANGUAGES": "en,es",
            "QUERY_EXPANSION_VARIANTS_PER_TERM": 1,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 10,
        }
    )
    settings = build_settings(config)
    diagnostics = {}
    expanded = expand_terms_to_queries(["counterfeit medicine"], settings, diagnostics=diagnostics)

    assert len(expanded) == 2
    assert diagnostics["ai_attempts"] == 2
    assert diagnostics["ai_fallbacks"] == 2
    assert diagnostics["ai_fallbacks_by_language"] == {"en": 1, "es": 1}
