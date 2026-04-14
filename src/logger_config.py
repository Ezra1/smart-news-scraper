import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Canonical logging configuration for the project; update here instead of any
# external logging.conf files.

_FILE_LOGGING_LOCK = threading.RLock()
_ROOT_FILE_LOGGING_INITIALIZED = False

# Single rotating file on the root logger — avoids per-module FileHandler(mode="w")
# truncating the same path and preserves fetch logs for the whole process.
_LOG_MAX_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 5


class EncodingStreamHandler(logging.StreamHandler):
    """StreamHandler that tolerates encoding errors and closed streams."""

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            if not stream or getattr(stream, "closed", False):
                return

            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                safe_msg = msg.encode(stream.encoding, errors="replace").decode(stream.encoding)
                stream.write(safe_msg + self.terminator)
            except (ValueError, OSError):
                return

            try:
                self.flush()
            except (ValueError, OSError):
                return
        except Exception:
            self.handleError(record)


def _log_file_path() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir / "news_scraper.log"


def _ensure_root_file_and_console_handlers() -> None:
    """Attach one rotating file handler and one console handler to the root logger."""
    global _ROOT_FILE_LOGGING_INITIALIZED
    with _FILE_LOGGING_LOCK:
        if _ROOT_FILE_LOGGING_INITIALIZED:
            return

        root = logging.getLogger()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        log_file = _log_file_path()
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        console_handler = EncodingStreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        root.setLevel(logging.INFO)
        _ROOT_FILE_LOGGING_INITIALIZED = True


def reset_logging_for_tests() -> None:
    """Remove root handlers and allow re-initialization. For tests only."""
    global _ROOT_FILE_LOGGING_INITIALIZED
    with _FILE_LOGGING_LOCK:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        _ROOT_FILE_LOGGING_INITIALIZED = False


def setup_logging(name: str = None) -> logging.Logger:
    """
    Return a module logger. File + console logging is configured once on the
    root logger so the log file is not truncated by repeated imports.

    Args:
        name: Logger name (typically __name__). None returns the root logger.
    Returns:
        logging.Logger: Configured logger instance (propagates to root).
    """
    _ensure_root_file_and_console_handlers()

    logger = logging.getLogger(name) if name else logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger
