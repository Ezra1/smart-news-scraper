from typing import Dict, Optional

from src.database_manager import DatabaseManager
from src.news_scraper import NewsArticleScraper
from src.article_validator import ArticleValidator
from src.openai_relevance_processing import ArticleProcessor
from src.config import ConfigManager


def create_pipeline(db_path: Optional[str] = None, config_manager: Optional[ConfigManager] = None) -> Dict[str, object]:
    """Create a configured pipeline with shared components for CLI and GUI."""
    config = config_manager or ConfigManager()
    db = DatabaseManager(db_path) if db_path else DatabaseManager()

    return {
        "config": config,
        "db_manager": db,
        "scraper": NewsArticleScraper(config, db_manager=db),
        "validator": ArticleValidator(),
        "processor": ArticleProcessor(db_manager=db, config_manager=config),
    }

