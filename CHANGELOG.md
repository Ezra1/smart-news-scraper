# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- High-recall multilingual query expansion with language-first controls in the GUI and config-driven language/region planning.
- Deterministic fallback translation maps for query expansion when AI expansion is unavailable.

### Changed
- Migrated article retrieval integration from Event Registry to TheNewsAPI.
- Updated AI relevance instructions to emphasize incident-focused scoring and concrete, actionable events.
- Hardened processing pipeline behavior and shared normalization paths for more consistent ingestion and relevance runs.

### Fixed
- Corrected defaults and diagnostics for zero-result fetch scenarios.
- Addressed GUI stability issues and improved release/build documentation and tooling guidance.

## [1.0.0] - 2025-06-20
### Added
- Initial public release of Smart News Scraper.
- Included standard documentation and packaging files.
- Added pharmaceutical search terms list and AI context prompt for security relevance.
