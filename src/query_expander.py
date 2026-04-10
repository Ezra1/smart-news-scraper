from dataclasses import dataclass
import json
from typing import Dict, List

from src.logger_config import setup_logging
from src.openai_client import get_client
from src.request_budget import QueryPlanItem

logger = setup_logging(__name__)

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
        "tr": ["sahte ilac", "taklit ilac", "falsifiye ilac"],
        "id": ["obat palsu", "obat tiruan", "pemalsuan obat"],
        "vi": ["thuoc gia", "thuoc nhai", "thuoc bi lam gia"],
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
        "tr": ["ele gecirilen ilac", "ilac operasyonu", "ilaclara el koyma"],
        "id": ["obat disita", "penyitaan obat", "obat berhasil disita"],
        "vi": ["thuoc bi thu giu", "thu giu thuoc", "thuoc bi tich thu"],
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
        "tr": ["kacak ilac", "ilac kacakciligi", "yasadisi ilac ticareti"],
        "id": ["obat selundupan", "penyelundupan obat", "perdagangan obat ilegal"],
        "vi": ["thuoc buôn lau", "buôn lau thuoc", "buôn ban thuoc bat hop phap"],
    },
}


@dataclass(frozen=True)
class ExpansionSettings:
    enabled: bool
    use_ai: bool
    languages: List[str]
    variants_per_term: int
    max_total_queries: int


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
    )


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
                        priority=priority,
                    )
                )
                if len(queries) >= settings.max_total_queries:
                    return queries

    return queries

