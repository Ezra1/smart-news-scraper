import os
import sys
import logging
from pathlib import Path

def setup_logging(name: str = None) -> logging.Logger:
    """
    Configure logging for the entire application.
    
    Args:
        name: Optional logger name (default: None - root logger)
    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logs directory in project root
    project_root = Path(__file__).resolve().parent.parent
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Main log file
    log_file = log_dir / "news_scraper.log"
    
    # Configure logging with both file and console handlers
    # Use UTF-8 encoding for file handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    
    # For console output, create a custom StreamHandler with error handling
    class EncodingStreamHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                stream = self.stream
                # Write with error handling for encoding issues
                try:
                    stream.write(msg + self.terminator)
                except UnicodeEncodeError:
                    # Fall back to replacing problematic characters
                    stream.write(msg.encode(stream.encoding, errors='replace').decode(stream.encoding) + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)
    
    console_handler = EncodingStreamHandler(sys.stdout)
    
    handlers = [file_handler, console_handler]
    
    # Set format for all handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Get logger
    logger = logging.getLogger(name) if name else logging.getLogger()
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Add and configure handlers
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    # Set logging level
    logger.setLevel(logging.INFO)
    
    return logger
