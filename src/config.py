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
        """Load configuration from the main project directory or create default if missing."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding="utf-8") as f:
                    user_config = json.load(f)
                    return {**DEFAULT_CONFIG, **user_config}  # Merge defaults with user config
            except json.JSONDecodeError as e:
                logging.error(f"Error reading config file: {e}")
                return DEFAULT_CONFIG
        else:
            self.save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG

    def _setup_logging(self):
        """Set up logging configuration."""
        log_file = Path(self.config_path).parent / "news_scraper.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)  # Ensure directory exists

        logging.basicConfig(
            level=getattr(logging, self.config.get("LOGGING_LEVEL", "INFO")),
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to the main project directory."""
        try:
            with open(self.config_path, 'w', encoding="utf-8") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
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
            logging.error(f"❌ Missing required configuration keys: {', '.join(missing_keys)}")
            return False
        return True

if __name__ == "__main__":
    config_manager = ConfigManager()

    # Prompt user to enter missing API keys
    if not config_manager.validate():
        print("\n❌ Configuration error: Missing API keys.")
        print("Please update your config.json file at:", config_manager.config_path)
        
        # Prompt user to enter missing keys interactively
        for key in ["NEWS_API_KEY", "OPENAI_API_KEY"]:
            if not config_manager.get(key):
                new_value = input(f"Enter {key}: ").strip()
                if new_value:
                    config_manager.set(key, new_value)
        
        # Validate again
        if not config_manager.validate():
            print("⚠️ Exiting. Fix missing API keys and restart.")
            exit(1)

    print("✅ Configuration loaded successfully.")
