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
    assert expanded[0].language == "en"
