"""Pre-filter articles before LLM scoring to save API costs."""

import re
from typing import Optional, Tuple

STRONG_ENFORCEMENT_KEYWORDS = {
    "seized",
    "seizure",
    "confiscated",
    "interdicted",
    "intercepted",
    "raided",
    "raid",
    "arrested",
    "arrest",
    "charged",
    "indicted",
    "prosecuted",
    "dismantled",
    "busted",
    "recall",
    "recalled",
}

WEAK_ENFORCEMENT_KEYWORDS = {
    "customs",
    "border",
    "police",
    "prosecutor",
    "recall",
    "warning",
    "warning letter",
    "inspection",
    "investigation",
    "investigating",
    "probe",
    "enforcement",
    "fda",
    "ema",
    "mhra",
    "interpol",
    "europol",
    "dea",
    "health canada",
    "tga",
    "anvisa",
    "who",
    "ministry of health",
    "health ministry",
    "drug regulator",
}

CRIME_DESCRIPTOR_KEYWORDS = {
    "smuggling",
    "smuggled",
    "trafficking",
    "counterfeit",
    "falsified",
    "illicit",
    "unauthorized",
    "diversion",
    "tampering",
}

PHARMA_KEYWORDS = {
    "medicine",
    "medicines",
    "medication",
    "medications",
    "pharmaceutical",
    "pharma",
    "drug",
    "prescription",
    "injectable",
    "vial",
    "tablets",
    "pills",
    "semaglutide",
    "tirzepatide",
    "glp-1",
    "insulin",
    "antibiotic",
    "steroid",
    "peptide",
    "sarm",
    "hormone",
}

COMMENTARY_KEYWORDS = {
    "trend",
    "trends",
    "policy",
    "opinion",
    "editorial",
    "commentary",
    "analysis",
    "outlook",
    "forecast",
    "discussion",
}


def _compile_keyword_pattern(keywords: set[str]) -> re.Pattern[str]:
    escaped = [re.escape(keyword) for keyword in sorted(keywords, key=len, reverse=True)]
    return re.compile(rf"(?<!\w)(?:{'|'.join(escaped)})(?!\w)", re.IGNORECASE)


_STRONG_ENFORCEMENT_PATTERN = _compile_keyword_pattern(STRONG_ENFORCEMENT_KEYWORDS)
_WEAK_ENFORCEMENT_PATTERN = _compile_keyword_pattern(WEAK_ENFORCEMENT_KEYWORDS)
_CRIME_DESCRIPTOR_PATTERN = _compile_keyword_pattern(CRIME_DESCRIPTOR_KEYWORDS)
_PHARMA_PATTERN = _compile_keyword_pattern(PHARMA_KEYWORDS)
_COMMENTARY_PATTERN = _compile_keyword_pattern(COMMENTARY_KEYWORDS)


def _has(pattern: re.Pattern[str], text: str) -> bool:
    return bool(pattern.search(text or ""))


def _is_non_english_text(text: str) -> bool:
    """Heuristic: detect likely non-English text to avoid false pre-LLM skips."""
    sample = str(text or "")
    if not sample.strip():
        return False
    ascii_letters = sum(1 for ch in sample if ("a" <= ch.lower() <= "z"))
    non_ascii_letters = sum(1 for ch in sample if ch.isalpha() and ord(ch) > 127)
    if non_ascii_letters == 0:
        return False
    total_letters = ascii_letters + non_ascii_letters
    if total_letters <= 0:
        return False
    # Treat as non-English when non-ASCII script dominates.
    return (non_ascii_letters / total_letters) >= 0.30


def is_incident_article(text: str) -> Tuple[bool, bool, bool]:
    """Check if article likely describes a pharma crime incident.

    Returns: (is_incident, has_enforcement, has_pharma)
    """
    normalized = text or ""
    has_pharma = _has(_PHARMA_PATTERN, normalized)
    has_strong_enforcement = _has(_STRONG_ENFORCEMENT_PATTERN, normalized)
    has_weak_enforcement = _has(_WEAK_ENFORCEMENT_PATTERN, normalized)
    has_crime_descriptor = _has(_CRIME_DESCRIPTOR_PATTERN, normalized)
    has_commentary = _has(_COMMENTARY_PATTERN, normalized)

    # Weak authority terms (e.g., "police", "inspection") need an explicit crime cue.
    has_enforcement = has_strong_enforcement or (has_weak_enforcement and has_crime_descriptor)
    is_incident = has_pharma and has_enforcement

    # Suppress policy/trend commentary unless there is concrete event language.
    if has_commentary and not has_strong_enforcement and not has_crime_descriptor:
        is_incident = False
        has_enforcement = False

    return (is_incident, has_enforcement, has_pharma)


def should_skip_llm(title: str, content: str, query_language: str = "") -> Tuple[bool, Optional[float]]:
    """Determine if we can skip LLM and assign score directly.

    Returns: (skip_llm, default_score)
    """
    combined = f"{title or ''} {content or ''}"
    normalized_query_language = str(query_language or "").strip().lower()
    if normalized_query_language and normalized_query_language != "en":
        return (False, None)
    if _is_non_english_text(combined):
        return (False, None)

    _, has_enforcement, has_pharma = is_incident_article(combined)

    if not has_pharma:
        return (True, 0.0)  # Not pharma-related at all
    if not has_enforcement:
        return (True, 0.3)  # Pharma but no incident language
    return (False, None)  # Send to LLM

