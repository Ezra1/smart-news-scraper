from dataclasses import dataclass
import json
from typing import Dict, List

from src.logger_config import setup_logging
from src.openai_client import get_client
from src.request_budget import QueryPlanItem

logger = setup_logging(__name__)

DEFAULT_LANGUAGE_REGION_MAP: Dict[str, List[str]] = {
    "en": ["us", "gb", "ca", "au"],
    "es": ["es", "mx", "ar", "co"],
    "fr": ["fr", "be", "ca"],
    "pt": ["pt", "br"],
    "ar": ["ae", "sa", "eg"],
    "ru": ["ru", "kz"],
    "zh": ["cn", "hk", "sg", "tw"],
    "hi": ["in"],
}

FALLBACK_TRANSLATIONS: Dict[str, Dict[str, List[str]]] = {
    "counterfeit medicine": {
        "en": ["counterfeit medicine", "fake medicine", "falsified medicine"],
        "es": ["medicamentos falsificados", "medicina falsa", "falsificacion de medicamentos"],
        "fr": ["medicaments contrefaits", "faux medicaments", "medicament falsifie"],
        "pt": ["medicamentos falsificados", "medicamento falso", "falsificacao de medicamentos"],
        "ar": ["ادوية مزيفة", "عقاقير مزيفة", "تزييف الادوية"],
        "ru": ["poddelnye lekarstva", "kontrafaktnye lekarstva", "falshivye medikamenty"],
        "zh": ["假药", "伪劣药品", "药品造假"],
        "hi": ["nakli davai", "jhooti davai", "dawai milawat"],
    },
    "seized medicine": {
        "en": ["seized medicine", "medicine seizure", "drug seizure"],
        "es": ["medicamentos incautados", "incautacion de medicamentos", "decomiso de medicamentos"],
        "fr": ["medicaments saisis", "saisie de medicaments", "saisie pharmaceutique"],
        "pt": ["medicamentos apreendidos", "apreensao de medicamentos", "sequestro de medicamentos"],
        "ar": ["ضبط ادوية", "مصادرة ادوية", "حجز ادوية"],
        "ru": ["izyatye lekarstva", "konfiskaciya lekarstv", "zaderzhanie lekarstv"],
        "zh": ["查获药品", "药品缉获", "查扣药品"],
        "hi": ["jabt davai", "dawai jabti", "zabt ki gayi davai"],
    },
    "smuggled medicine": {
        "en": ["smuggled medicine", "medicine trafficking", "illicit medicine trade"],
        "es": ["medicamentos de contrabando", "trafico de medicamentos", "comercio ilegal de medicamentos"],
        "fr": ["medicaments de contrebande", "trafic de medicaments", "commerce illegal de medicaments"],
        "pt": ["medicamentos contrabandeados", "trafico de medicamentos", "comercio ilegal de medicamentos"],
        "ar": ["تهريب ادوية", "اتجار غير مشروع بالادوية", "شبكة تهريب ادوية"],
        "ru": ["kontrabandnye lekarstva", "trafik lekarstv", "nelegalnaya torgovlya lekarstvami"],
        "zh": ["走私药品", "药品走私", "非法药品贸易"],
        "hi": ["smuggle ki hui davai", "dawai taskari", "avaidh dava vyapar"],
    },
}


@dataclass(frozen=True)
class ExpansionSettings:
    enabled: bool
    use_ai: bool
    languages: List[str]
    variants_per_term: int
    max_total_queries: int
    auto_region_mapping: bool
    region_override_enabled: bool
    override_regions: List[str]


def _parse_csv_values(raw: str) -> List[str]:
    if not raw:
        return []
    return [part.strip().lower() for part in str(raw).split(",") if part.strip()]


def build_settings(config_manager) -> ExpansionSettings:
    return ExpansionSettings(
        enabled=bool(config_manager.get("QUERY_EXPANSION_ENABLED", True)),
        use_ai=bool(config_manager.get("QUERY_EXPANSION_USE_AI", True)),
        languages=_parse_csv_values(config_manager.get("QUERY_EXPANSION_LANGUAGES", "en")),
        variants_per_term=max(1, int(config_manager.get("QUERY_EXPANSION_VARIANTS_PER_TERM", 3))),
        max_total_queries=max(1, int(config_manager.get("QUERY_EXPANSION_MAX_TOTAL_QUERIES", 120))),
        auto_region_mapping=bool(config_manager.get("AUTO_REGION_MAPPING_ENABLED", True)),
        region_override_enabled=bool(config_manager.get("REGION_OVERRIDE_ENABLED", False)),
        override_regions=_parse_csv_values(config_manager.get("QUERY_EXPANSION_REGIONS", "")),
    )


def _regions_for_language(language: str, settings: ExpansionSettings) -> List[str]:
    if settings.region_override_enabled and settings.override_regions:
        return settings.override_regions
    if not settings.auto_region_mapping:
        return []
    return DEFAULT_LANGUAGE_REGION_MAP.get(language, [])


def _expand_with_fallback(term: str, language: str, variants_per_term: int) -> List[str]:
    normalized_term = str(term or "").strip().lower()
    from_map = FALLBACK_TRANSLATIONS.get(normalized_term, {})
    values = from_map.get(language, [term])
    if language == "en" and term not in values:
        values = [term] + values
    return values[:variants_per_term]


def _expand_with_ai(term: str, language: str, variants_per_term: int, model: str = "gpt-4o-mini") -> List[str]:
    try:
        client = get_client()
    except Exception as exc:
        logger.warning("AI query expansion unavailable: %s", exc)
        return _expand_with_fallback(term, language, variants_per_term)

    prompt = (
        "Return a JSON array of concise search phrases for news retrieval. "
        f"Base term: '{term}'. Target language code: '{language}'. "
        f"Return at most {variants_per_term} items. Keep it incident/security focused. "
        "No explanation text, only JSON array."
    )

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content or "[]"
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            return _expand_with_fallback(term, language, variants_per_term)
        values = [str(item).strip() for item in parsed if str(item).strip()]
        if not values:
            return _expand_with_fallback(term, language, variants_per_term)
        return values[:variants_per_term]
    except Exception as exc:
        logger.warning("AI query expansion failed for term='%s' language='%s': %s", term, language, exc)
        return _expand_with_fallback(term, language, variants_per_term)


def expand_terms_to_queries(
    terms: List[str],
    settings: ExpansionSettings,
) -> List[QueryPlanItem]:
    if not terms:
        return []

    queries: List[QueryPlanItem] = []
    dedup = set()

    effective_languages = settings.languages or ["en"]
    for priority, root_term in enumerate(terms):
        if not isinstance(root_term, str) or not root_term.strip():
            continue
        root_term = root_term.strip()

        for language in effective_languages:
            language = language.strip().lower()
            if not language:
                continue
            if settings.enabled:
                if settings.use_ai:
                    candidates = _expand_with_ai(root_term, language, settings.variants_per_term)
                else:
                    candidates = _expand_with_fallback(root_term, language, settings.variants_per_term)
            else:
                candidates = [root_term]

            for candidate in candidates:
                query = str(candidate).strip()
                if not query:
                    continue
                dedup_key = (root_term.lower(), language, query.lower())
                if dedup_key in dedup:
                    continue
                dedup.add(dedup_key)
                queries.append(
                    QueryPlanItem(
                        term=query,
                        root_term=root_term,
                        language=language,
                        regions=_regions_for_language(language, settings),
                        priority=priority,
                    )
                )
                if len(queries) >= settings.max_total_queries:
                    return queries

    return queries

