import base64
import os
import json
from pathlib import Path
from typing import Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

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
    "DATABASE_PATH": "data/news_articles.db",
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
        self.keys_path = str(Path(self.config_path).parent / ".api_keys")
        self._encryption_key = self._get_encryption_key()
        self.config = self._load_config()

    def get_config_path(self) -> str:
        """Ensure config.json is stored in the config directory."""
        project_root = Path(__file__).resolve().parent.parent
        return str(project_root / "config" / "config.json")

    def _get_encryption_key(self) -> bytes:
        """
        Get or create encryption key for API keys.
        
        Uses a more secure approach with a random salt stored in a separate file.
        """
        key_file = Path(self.keys_path + ".key")
        salt_file = Path(self.keys_path + ".salt")
        
        # If key already exists, return it
        if key_file.exists() and salt_file.exists():
            return key_file.read_bytes()
        
        # Generate new key with random salt
        import os
        import getpass
        import hashlib
        
        # Generate a random salt
        salt = os.urandom(16)
        salt_file.write_bytes(salt)
        
        # Use machine-specific information as a base for the password
        # This isn't perfect security but better than a hardcoded password
        machine_id = hashlib.md5(os.uname().nodename.encode()).hexdigest()
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))
        key_file.write_bytes(key)
        
        return key

    def _save_api_keys(self, keys: dict):
        """Save API keys encrypted."""
        try:
            f = Fernet(self._encryption_key)
            encrypted_data = f.encrypt(json.dumps(keys).encode())
            with open(self.keys_path, 'wb') as file:
                file.write(encrypted_data)
        except Exception as e:
            logger.error(f"Error saving API keys: {e}")

    def _load_api_keys(self) -> dict:
        """Load encrypted API keys."""
        try:
            if not os.path.exists(self.keys_path):
                return {}
            
            f = Fernet(self._encryption_key)
            with open(self.keys_path, 'rb') as file:
                encrypted_data = file.read()
            decrypted_data = f.decrypt(encrypted_data)
            return json.loads(decrypted_data)
        except Exception as e:
            logger.error(f"Error loading API keys: {e}")
            return {}

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration with secure handling of credentials"""
        config = {}
        
        # Load saved API keys first
        api_keys = self._load_api_keys()
        config.update(api_keys)
        
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
                except (ValueError, TypeError) as e:
                    logger.error(f"Error converting environment variable {key}: {e}")
                    config[key] = DEFAULT_CONFIG[key]

        # Then load from file, allowing file values to override env vars
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding="utf-8") as f:
                    file_config = json.load(f)
                    config.update(file_config)
            except json.JSONDecodeError as e:
                logger.error(f"Config file error: {e}")
        else:
            # Create default config file if it doesn't exist
            self.save_config(DEFAULT_CONFIG)

        # Fill in any missing values from defaults
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
        
        return config

    def save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration with secure API key handling"""
        try:
            # Extract API keys
            api_keys = {
                key: config[key]
                for key in ['NEWS_API_KEY', 'OPENAI_API_KEY']
                if key in config and config[key]
            }
            
            # Save API keys separately if they exist
            if api_keys:
                self._save_api_keys(api_keys)
            
            # Save rest of config without API keys
            safe_config = {k: v for k, v in config.items() if k not in api_keys}
            with open(self.config_path, 'w', encoding="utf-8") as f:
                json.dump(safe_config, f, indent=4)
                
            # Update running config
            self.config.update(config)
            
            logger.info("Config and API keys saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving config: {e}")
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