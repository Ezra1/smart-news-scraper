import logging
from logging.handlers import RotatingFileHandler

import pytest

from src.logger_config import _log_file_path, reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging_between_tests():
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()


def test_setup_logging_configures_root_once_and_preserves_lines():
    log_path = _log_file_path()
    if log_path.exists():
        log_path.unlink()

    root = logging.getLogger()
    logger_a = setup_logging("test.package.a")
    logger_a.info("first-line")

    logger_b = setup_logging("test.package.b")
    logger_b.info("second-line")

    assert logger_a.handlers == []
    assert logger_b.handlers == []
    assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)

    for handler in root.handlers:
        try:
            handler.flush()
        except Exception:
            pass

    text = log_path.read_text(encoding="utf-8")
    assert "first-line" in text
    assert "second-line" in text


def test_setup_logging_third_call_does_not_add_duplicate_root_file_handlers():
    setup_logging("x")
    setup_logging("y")
    setup_logging("z")
    root = logging.getLogger()
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
