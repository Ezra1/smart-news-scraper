import logging
from pathlib import Path

from src.logger_config import setup_logging


def test_setup_logging_creates_logger_and_logfile():
    log_path = Path(__file__).resolve().parent.parent / "logs" / "news_scraper.log"

    if log_path.exists():
        log_path.unlink()

    logger = setup_logging("test-logger")
    logger.info("logging smoke test")

    assert isinstance(logger, logging.Logger)
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    assert log_path.exists()

    for handler in logger.handlers[:]:
        handler.flush()
        logger.removeHandler(handler)

    if log_path.exists():
        log_path.unlink()

