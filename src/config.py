import os
import json
from pathlib import Path
from typing import Dict, Any

from src.logger_config import setup_logging
logger = setup_logging(__name__)

# Default Configuration
DEFAULT_CONFIG = {
    "NEWS_API_KEY": "",
    "OPENAI_API_KEY": "",
    "NEWS_API_URL": "https://newsapi.org/v2/everything",
    "NEWS_API_DAILY_LIMIT": 100,
    "NEWS_API_REQUESTS_PER_SECOND": 1,
    "OPENAI_REQUESTS_PER_MINUTE": 60,  # Add missing OpenAI rate limit
    "RELEVANCE_THRESHOLD": 0.6,
    "BATCH_SIZE": 100,
    "DATABASE_PATH": "news_articles.db",
    "LOGGING_LEVEL": "INFO",
    "OUTPUT_DIR": "output",
    "CHATGPT_CONTEXT_MESSAGE": {  # Add default system message
        "role": "system",
        "content": "You are an AI trained to analyze news articles for relevance. Rate each article's relevance from 0.0 to 1.0."
    }
}

class ConfigManager:
    def __init__(self):
        """Initialize config manager and load config file from the project root."""
        self.config_path = self.get_config_path()
        self.config = self._load_config()

    def get_config_path(self) -> str:
        """Ensure config.json is stored in the main project directory, not src/."""
        project_root = Path(__file__).resolve().parent.parent
        return str(project_root / "config.json")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration with secure handling of credentials"""
        config = {}
        in_memory_keys = {}
        
        # Load from environment variables first with type conversion
        type_map = {
            "NEWS_API_DAILY_LIMIT": int,
            "NEWS_API_REQUESTS_PER_SECOND": int,
            "OPENAI_REQUESTS_PER_MINUTE": int,
            "BATCH_SIZE": int,
            "RELEVANCE_THRESHOLD": float
        }
        
        # First load from environment
        for key in DEFAULT_CONFIG:
            env_value = os.getenv(f"NEWS_SCRAPER_{key}")
            if env_value:
                try:
                    if key in type_map:
                        config[key] = type_map[key](env_value)
                    else:
                        config[key] = env_value
                        # Store API keys from env vars
                        if key in ['NEWS_API_KEY', 'OPENAI_API_KEY'] and env_value:
                            in_memory_keys[key] = env_value
                except (ValueError, TypeError) as e:
                    logger.error(f"Error converting environment variable {key}: {e}")
                    config[key] = DEFAULT_CONFIG[key]

        # Then load from file, allowing file values to override env vars
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding="utf-8") as f:
                    file_config = json.load(f)
                    # Merge file config, preserving API keys
                    for key, value in file_config.items():
                        if key in ['NEWS_API_KEY', 'OPENAI_API_KEY'] and value:
                            in_memory_keys[key] = value
                        elif value:  # Only use non-empty values from file
                            config[key] = value
            except json.JSONDecodeError as e:
                logger.error(f"Config file error: {e}")
        else:
            # Create default config file if it doesn't exist
            self.save_config(DEFAULT_CONFIG)

        # Fill in any missing values from defaults
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value

        # Restore API keys from memory
        config.update(in_memory_keys)
        
        return config

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration with secure API key handling"""
        try:
            # Store current API keys in memory
            api_keys = {
                key: config.get(key, '') 
                for key in ['NEWS_API_KEY', 'OPENAI_API_KEY']
            }
            
            # Create safe config for file
            safe_config = config.copy()
            for key in api_keys:
                safe_config[key] = ''  # Clear sensitive values for file
            
            # Write safe config to file
            with open(self.config_path, 'w', encoding="utf-8") as f:
                json.dump(safe_config, f, indent=4)
            
            # Update in-memory config with API keys
            self.config.update(api_keys)
            
            logger.info("Config saved successfully with API keys preserved")
            
        except (OSError, IOError) as e:
            logger.error(f"Error saving config file: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value and save to file."""
        self.config[key] = value
        self.save_config(self.config)

    def validate(self) -> bool:
        """Enhanced validation of configuration values"""
        # Check required API keys
        required_keys = ["NEWS_API_KEY", "OPENAI_API_KEY"]
        missing_keys = [key for key in required_keys if not self.config.get(key)]
        if missing_keys:
            logger.error(f"Missing required configuration keys: {', '.join(missing_keys)}")
            return False
            
        # Validate numeric ranges
        try:
            # Threshold validation
            threshold = self.config.get("RELEVANCE_THRESHOLD")
            if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                logger.error(f"Invalid RELEVANCE_THRESHOLD value: {threshold}. Must be between 0 and 1.")
                return False

            # Rate limit validations
            if self.config.get("NEWS_API_REQUESTS_PER_SECOND", 0) < 0:
                logger.error("NEWS_API_REQUESTS_PER_SECOND must be positive")
                return False

            if self.config.get("OPENAI_REQUESTS_PER_MINUTE", 0) < 0:
                logger.error("OPENAI_REQUESTS_PER_MINUTE must be positive")
                return False

            # Batch size validation
            if self.config.get("BATCH_SIZE", 0) <= 0:
                logger.error("BATCH_SIZE must be positive")
                return False

        except (TypeError, ValueError) as e:
            logger.error(f"Configuration validation error: {e}")
            return False
            
        logger.info("Configuration validated successfully")
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