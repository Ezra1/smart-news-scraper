from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional

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
    high_recall = bool(config_manager.get("HIGH_RECALL_MODE", True))
    maximum_recall = bool(config_manager.get("MAXIMUM_RECALL_MODE", False))
    raw_langs = _parse_csv_values(config_manager.get("QUERY_EXPANSION_LANGUAGES", "en"))
    languages = raw_langs or ["en"]
    if not high_recall:
        languages = ["en"]
    variants_per_term = max(1, int(config_manager.get("QUERY_EXPANSION_VARIANTS_PER_TERM", 3)))
    max_total_queries = max(1, int(config_manager.get("QUERY_EXPANSION_MAX_TOTAL_QUERIES", 120)))
    if maximum_recall:
        # Prefer breadth of query surface over duplicate near-synonyms.
        variants_per_term = max(variants_per_term, 10)
        max_total_queries = max(max_total_queries, 800)
    return ExpansionSettings(
        enabled=bool(config_manager.get("QUERY_EXPANSION_ENABLED", True)),
        use_ai=bool(config_manager.get("QUERY_EXPANSION_USE_AI", True)),
        languages=languages,
        variants_per_term=variants_per_term,
        max_total_queries=max_total_queries,
    )


def _expand_with_fallback(term: str, language: str, variants_per_term: int) -> List[str]:
    normalized_term = str(term or "").strip().lower()
    from_map = FALLBACK_TRANSLATIONS.get(normalized_term, {})
    values = from_map.get(language, [term])
    if language == "en" and term not in values:
        values = [term] + values
    return values[:variants_per_term]


def _extract_json_array(raw_content: str) -> Optional[List[Any]]:
    """Parse JSON array from raw/fenced/model output; return None when invalid."""
    if not isinstance(raw_content, str):
        return None
    content = raw_content.strip()
    if not content:
        return None

    def _loads_if_array(payload: str) -> Optional[List[Any]]:
        try:
            parsed = json.loads(payload)
        except Exception:
            return None
        return parsed if isinstance(parsed, list) else None

    direct = _loads_if_array(content)
    if direct is not None:
        return direct

    if content.startswith("```"):
        fence_start = content.find("\n")
        if fence_start != -1:
            fenced_payload = content[fence_start + 1 :]
            fence_end = fenced_payload.rfind("```")
            if fence_end != -1:
                fenced_payload = fenced_payload[:fence_end].strip()
            fenced = _loads_if_array(fenced_payload)
            if fenced is not None:
                return fenced

    start = content.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(content)):
        ch = content[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return _loads_if_array(content[start : idx + 1])
    return None


def _expand_with_ai(
    term: str,
    language: str,
    variants_per_term: int,
    model: str = "gpt-4o-mini",
    diagnostics: Optional[Dict[str, Any]] = None,
) -> List[str]:
    try:
        client = get_client()
    except Exception as exc:
        logger.warning("AI query expansion unavailable: %s", exc)
        if isinstance(diagnostics, dict):
            diagnostics["used_fallback"] = True
            diagnostics["fallback_reason"] = "client_unavailable"
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
        parsed = _extract_json_array(content)
        if not parsed:
            if isinstance(diagnostics, dict):
                diagnostics["used_fallback"] = True
                diagnostics["fallback_reason"] = "invalid_json_array"
            return _expand_with_fallback(term, language, variants_per_term)
        values = [str(item).strip() for item in parsed if str(item).strip()]
        if not values:
            if isinstance(diagnostics, dict):
                diagnostics["used_fallback"] = True
                diagnostics["fallback_reason"] = "empty_candidates"
            return _expand_with_fallback(term, language, variants_per_term)
        if isinstance(diagnostics, dict):
            diagnostics["used_fallback"] = False
            diagnostics["fallback_reason"] = ""
        return values[:variants_per_term]
    except Exception as exc:
        logger.warning("AI query expansion failed for term='%s' language='%s': %s", term, language, exc)
        if isinstance(diagnostics, dict):
            diagnostics["used_fallback"] = True
            diagnostics["fallback_reason"] = "api_exception"
        return _expand_with_fallback(term, language, variants_per_term)


def expand_terms_to_queries(
    terms: List[str],
    settings: ExpansionSettings,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> List[QueryPlanItem]:
    if isinstance(diagnostics, dict):
        diagnostics.update(
            {
                "ai_attempts": 0,
                "ai_fallbacks": 0,
                "ai_fallbacks_by_language": {},
                "expanded_queries_count": 0,
                "max_total_queries": settings.max_total_queries,
            }
        )
    if not terms:
        return []

    if not settings.enabled:
        queries: List[QueryPlanItem] = []
        seen_root: set[str] = set()
        for priority, root_term in enumerate(terms):
            if not isinstance(root_term, str) or not root_term.strip():
                continue
            root_term = root_term.strip()
            key = root_term.lower()
            if key in seen_root:
                continue
            seen_root.add(key)
            queries.append(
                QueryPlanItem(
                    term=root_term,
                    root_term=root_term,
                    language="",
                    priority=priority,
                )
            )
            if len(queries) >= settings.max_total_queries:
                break
        if isinstance(diagnostics, dict):
            diagnostics["expanded_queries_count"] = len(queries)
        return queries

    queries: List[QueryPlanItem] = []
    dedup = set()

    effective_languages = settings.languages or ["en"]
    ai_attempts = 0
    ai_fallbacks = 0
    ai_failures_by_language: Dict[str, int] = {}
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
                    ai_attempts += 1
                    expansion_diag: Dict[str, Any] = {}
                    candidates = _expand_with_ai(
                        root_term,
                        language,
                        settings.variants_per_term,
                        diagnostics=expansion_diag,
                    )
                    if expansion_diag.get("used_fallback"):
                        ai_fallbacks += 1
                        ai_failures_by_language[language] = ai_failures_by_language.get(language, 0) + 1
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
                    if isinstance(diagnostics, dict):
                        diagnostics.update(
                            {
                                "ai_attempts": ai_attempts,
                                "ai_fallbacks": ai_fallbacks,
                                "ai_fallbacks_by_language": dict(ai_failures_by_language),
                                "expanded_queries_count": len(queries),
                                "max_total_queries": settings.max_total_queries,
                            }
                        )
                    return queries

    if isinstance(diagnostics, dict):
        diagnostics.update(
            {
                "ai_attempts": ai_attempts,
                "ai_fallbacks": ai_fallbacks,
                "ai_fallbacks_by_language": dict(ai_failures_by_language),
                "expanded_queries_count": len(queries),
                "max_total_queries": settings.max_total_queries,
            }
        )
    return queries

