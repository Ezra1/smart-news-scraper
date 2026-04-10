# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [2.1.0] - 2026-04-10
### Added
- GUI multilingual picker aligned with TheNewsAPI supported language codes (including `multi`).
- Results tab: table columns for API-style fields (UUID, title, description, keywords, snippet, URL, image URL, language, published, source, categories, relevance).
- Export formats (JSON, CSV, plain text) include the same fields; JSON matches a TheNewsAPI article object shape (`categories` as array, `image_url`, `uuid`, etc.).
- Database columns on `raw_articles` and `relevant_articles` for API metadata (`api_uuid`, `description`, `snippet`, `keywords`, `language`, `api_categories`); loading results joins raw rows to backfill older relevant rows when possible.
- News fetch normalization passes `keywords` from the API into storage.

### Removed
- Geographic filtering: no `locale` query parameter, no language→region map, no region override config or GUI controls (`AUTO_REGION_MAPPING_ENABLED`, `REGION_OVERRIDE_ENABLED`, `QUERY_EXPANSION_REGIONS`).

### Changed
- `QueryPlanItem` and query expansion settings no longer carry regions; pipeline status text shows language only.
- Config template default `QUERY_EXPANSION_LANGUAGES` is `en`; README documents language-only expansion and removed region keys.
- Multilingual query expansion changelog wording and docs updated for the above.

### Fixed
- Corrected defaults and diagnostics for zero-result fetch scenarios (prior releases).
- GUI stability and processing pipeline robustness (prior cumulative fixes).

## [1.0.0] - 2025-06-20
### Added
- Initial public release of Smart News Scraper.
- Included standard documentation and packaging files.
- Added pharmaceutical search terms list and AI context prompt for security relevance.
