import os
import logging
from pathlib import Path

def setup_logging(config_dir: Path, level: str = "INFO") -> None:
    """
    Configure logging for the entire application.
    
    Args:
        config_dir: Directory where logs should be stored (usually project root)
        level: Logging level as string (default: "INFO")
    """
    # Create logs directory if it doesn't exist
    log_dir = config_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Main log file
    log_file = log_dir / "news_scraper.log"
    
    # Remove any existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Configure logging with both file and console handlers
    handlers = [
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
    
    # Set format for all handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    for handler in handlers:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    
    # Set logging level
    root_logger.setLevel(getattr(logging, level.upper()))
