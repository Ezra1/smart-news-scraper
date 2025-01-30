import os
import json
import logging
from pathlib import Path
from typing import Dict, Any

# Default Configuration
DEFAULT_CONFIG = {
    "NEWS_API_KEY": "",
    "OPENAI_API_KEY": "",
    "NEWS_API_URL": "https://newsapi.org/v2/everything",
    "NEWS_API_DAILY_LIMIT": 100,
    "NEWS_API_REQUESTS_PER_SECOND": 1,
    "RELEVANCE_THRESHOLD": 0.7,
    "BATCH_SIZE": 100,
    "DATABASE_PATH": "news_articles.db",
    "LOGGING_LEVEL": "INFO",
    "OUTPUT_DIR": "output"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        """Initialize config manager and load config file from the project root."""
        self.config_path = self.get_config_path()
        self.config = self._load_config()
        self._setup_logging()

    def get_config_path(self) -> str:
        """Ensure config.json is stored in the main project directory, not src/."""
        project_root = Path(__file__).resolve().parent.parent  # Go up from src/
        return str(project_root / "config.json")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration with secure handling of credentials"""
        config = {}
        
        # Load from environment variables first
        for key in DEFAULT_CONFIG:
            env_value = os.getenv(f"NEWS_SCRAPER_{key}")
            if env_value:
                config[key] = env_value

        # Load from config file, but don't override environment variables
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding="utf-8") as f:
                    file_config = json.load(f)
                    # Only use file values for keys not in environment
                    for key, value in file_config.items():
                        if key not in config:
                            config[key] = value
            except json.JSONDecodeError as e:
                logging.error(f"Config file error: {e}")
        else:
            # Create default config file if it doesn't exist
            self.save_config(DEFAULT_CONFIG)

        # Merge with defaults for any missing values
        return {**DEFAULT_CONFIG, **config}

    def _setup_logging(self):
        """Set up logging configuration."""
        log_file = Path(self.config_path).parent / "news_scraper.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, self.config.get("LOGGING_LEVEL", "INFO")),
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        logger.setLevel(getattr(logging, self.config.get("LOGGING_LEVEL", "INFO")))

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to the main project directory with secure handling."""
        try:
            # Filter out sensitive data before saving
            safe_config = config.copy()
            sensitive_keys = ['NEWS_API_KEY', 'OPENAI_API_KEY']
            
            for key in sensitive_keys:
                if key in safe_config and safe_config[key]:
                    safe_config[key] = ''  # Clear sensitive values when saving to file
            
            with open(self.config_path, 'w', encoding="utf-8") as f:
                json.dump(safe_config, f, indent=4)
        except (OSError, IOError) as e:
            logging.error(f"Error saving config file: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value and save to file."""
        self.config[key] = value
        self.save_config(self.config)

    def validate(self) -> bool:
        """Ensure required API keys exist."""
        required_keys = ["NEWS_API_KEY", "OPENAI_API_KEY"]
        missing_keys = [key for key in required_keys if not self.config.get(key)]

        if missing_keys:
            logging.error(f"Missing required configuration keys: {', '.join(missing_keys)}")
            return False
        return True

if __name__ == "__main__":
    config_manager = ConfigManager()

    # Prompt user to enter missing API keys
    if not config_manager.validate():
        print("\nConfiguration error: Missing API keys.")
        print("Please update your config.json file at:", config_manager.config_path)
        print("\nAlternatively, set environment variables:")
        print("NEWS_SCRAPER_NEWS_API_KEY")
        print("NEWS_SCRAPER_OPENAI_API_KEY")
        
        # Prompt user to enter missing keys interactively
        for key in ["NEWS_API_KEY", "OPENAI_API_KEY"]:
            if not config_manager.get(key):
                new_value = input(f"Enter {key}: ").strip()
                if new_value:
                    config_manager.set(key, new_value)
        
        # Validate again
        if not config_manager.validate():
            print("Exiting. Fix missing API keys and restart.")
            exit(1)

    print("Configuration loaded successfully.")