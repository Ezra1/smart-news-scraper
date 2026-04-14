"""Shared GUI constants (also used by export / table column mapping)."""

# Results table: field key, header label, default width (API-aligned export uses same keys).
RESULTS_TABLE_COLUMNS = [
    ("api_uuid", "Record ID", 200),
    ("title", "Title", 240),
    ("description", "Description", 200),
    ("keywords", "Keywords", 160),
    ("snippet", "Snippet", 180),
    ("url", "URL", 260),
    ("url_to_image", "Image URL", 200),
    ("language", "Language", 64),
    ("published_at", "Published", 168),
    ("source", "Source", 120),
    ("categories_display", "Categories", 140),
    ("relevance_score", "Relevance", 80),
]

RESULTS_TABLE_COLUMNS_ANALYST = [
    ("title", "Title", 320),
    ("source", "Source", 140),
    ("published_at", "Published", 168),
    ("relevance_score", "Relevance", 90),
    ("url", "URL", 360),
]

FILTER_PRESET_MAP = {
    "more_permissive": {
        "min_content_chars": 40,
        "max_content_chars": 40000,
        "min_query_token_overlap": 0,
        "require_incident_signal": False,
        "dedup_by_url": True,
        "dedup_by_title": True,
    },
    "medium": {
        "min_content_chars": 120,
        "max_content_chars": 20000,
        "min_query_token_overlap": 1,
        "require_incident_signal": False,
        "dedup_by_url": True,
        "dedup_by_title": True,
    },
    "most_aggressive": {
        "min_content_chars": 250,
        "max_content_chars": 12000,
        "min_query_token_overlap": 2,
        "require_incident_signal": True,
        "dedup_by_url": True,
        "dedup_by_title": True,
    },
}

# Codes align with TheNewsAPI supported languages.
SUPPORTED_LANGUAGES = [
    ("ar", "Arabic"),
    ("bg", "Bulgarian"),
    ("bn", "Bengali"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("et", "Estonian"),
    ("fa", "Persian"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("hr", "Croatian"),
    ("hu", "Hungarian"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("lt", "Lithuanian"),
    ("nl", "Dutch"),
    ("no", "Norwegian"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("sv", "Swedish"),
    ("ta", "Tamil"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
    ("zh", "Chinese"),
]
