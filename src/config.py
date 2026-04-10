import base64
import os
import json
import platform
import uuid
import hashlib
import stat
from pathlib import Path
from typing import Dict, Any, List
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src.logger_config import setup_logging
logger = setup_logging(__name__)

DEFAULT_CONTEXT_MESSAGE = {
    "role": "system",
    "content": (
        "You are an intelligence relevance classifier for a pharmaceutical security "
        "analysis team.\n\n"
        "Your task is to assess whether a news article contains information relevant "
        "to pharmaceutical security threats and assign a relevance score.\n\n"
        "RELEVANCE CRITERIA (STRICT)\n\n"
        "Relevant content includes specific, real-world incidents or risks involving:\n\n"
        "Counterfeit or falsified medicines\n"
        "Theft, diversion, or illegal resale of pharmaceuticals\n"
        "Smuggling or trafficking involving pharmaceutical products\n"
        "Supply chain compromise or disruption (manufacturing, distribution, logistics)\n"
        "Regulatory or law enforcement actions related to pharmaceutical crime\n"
        "Cyberattacks targeting pharmaceutical companies or infrastructure\n"
        "Product tampering, contamination, or integrity threats\n"
        "EXCLUDE (NOT RELEVANT)\n\n"
        "Do NOT consider relevant:\n\n"
        "General healthcare or medical news\n"
        "Business/financial news without a security component\n"
        "Public health trends without criminal or security relevance\n"
        "Opinion or analysis without concrete events\n"
        "SCORING GUIDANCE\n\n"
        "Assign a relevance_score from 0.0 to 1.0:\n\n"
        "0.0-0.2 -> Not relevant\n"
        "0.3-0.5 -> Weak or indirect relevance\n"
        "0.6-0.8 -> Moderate relevance (clear issue, limited specificity or impact)\n"
        "0.9-1.0 -> High relevance (direct, specific, actionable threat)\n"
        "DECISION RULES\n"
        "Prioritize pharmaceutical security content only, ignore unrelated portions\n"
        "If relevance is partial, score proportionally\n"
        "Default lower if uncertain or evidence is vague\n"
        "Favor specific incidents, actors, or enforcement actions over general discussion\n"
        "EXPLANATION REQUIREMENT\n\n"
        "Provide a concise explanation (1-2 sentences) that:\n\n"
        "References the specific element that triggered relevance\n"
        "Uses concrete language (no vague summaries)"
    ),
}

# Default Configuration
DEFAULT_CONFIG = {
    "NEWS_API_KEY": "",
    "OPENAI_API_KEY": "",
    "NEWS_API_BASE_URL": "https://api.thenewsapi.com/v1/news",
    "NEWS_API_DAILY_LIMIT": 100,
    "NEWS_API_REQUESTS_PER_SECOND": 1,
    "NEWS_API_PAGE_LIMIT": 50,
    "FETCH_MAX_PAGES_PER_QUERY": 5,
    "NEWS_API_LANGUAGE": "en",
    "NEWS_SOURCE_ALLOWLIST": "",
    "NEWS_SOURCE_BLOCKLIST": "",
    "NEWS_API_MIN_BODY_LENGTH": 600,
    "NEWS_API_ENABLE_URL_FALLBACK": True,
    "NEWS_API_URL_FALLBACK_TIMEOUT_SECONDS": 15,
    "NEWS_API_URL_FALLBACK_MAX_CONCURRENCY": 8,
    "RAW_ARTICLE_INSERT_BATCH_SIZE": 100,
    "PRELLM_ENABLE_FILTERING": True,
    "PRELLM_MIN_CONTENT_CHARS": 120,
    "PRELLM_MAX_CONTENT_CHARS": 20000,
    "PRELLM_MIN_QUERY_TOKEN_OVERLAP": 1,
    "PRELLM_REQUIRE_INCIDENT_SIGNAL": False,
    "PRELLM_DEDUP_BY_URL": True,
    "PRELLM_DEDUP_BY_TITLE": True,
    "PRELLM_TOP_K_PER_TERM": 100,
    "PRELLM_STAGE3_ENABLED": False,
    "PRELLM_LOG_DROPS": True,
    "PRELLM_ENABLE_LLM_GUARDRAIL": True,
    "PRELLM_FILTER_PRESET": "more_permissive",
    "PRELLM_TOPIC_OVERRIDES": {},
    "OPENAI_REQUESTS_PER_MINUTE": 60,
    "RELEVANCE_THRESHOLD": 0.7,
    "QUERY_EXPANSION_ENABLED": True,
    "QUERY_EXPANSION_USE_AI": True,
    "QUERY_EXPANSION_VARIANTS_PER_TERM": 3,
    "QUERY_EXPANSION_MAX_TOTAL_QUERIES": 120,
    "QUERY_EXPANSION_LANGUAGES": "en,es,fr,pt,ar,ru,zh,hi",
    "REQUEST_BUDGET_MODE": "aggressive",
    "REQUEST_BUDGET_PER_RUN": 200,
    "DATE_RANGE_MODE": "preset",
    "DATE_RANGE_PRESET": "Last 7 days",
    "DATE_RANGE_AFTER": "",
    "DATE_RANGE_BEFORE": "",
    "DATE_RANGE_ON": "",
    "BATCH_SIZE": 100,
    "DATABASE_PATH": "data/news_articles.db",
    "LOGGING_LEVEL": "INFO",
    "OUTPUT_DIR": "output",
}

EXPECTED_API_URL = "https://api.thenewsapi.com/v1/news"
EXPECTED_DB_PATH = "data/news_articles.db"
EXPECTED_THRESHOLD = 0.7


def _first_non_null(config: Dict[str, Any], *keys: str) -> Any:
    """Return the first key in config with a non-None value."""
    for key in keys:
        if key in config and config[key] is not None:
            return config[key]
    return None


def validate_config(config: Dict[str, Any]) -> List[str]:
    """Return list of warnings if config diverges from expected defaults."""
    warnings: List[str] = []

    api_url = _first_non_null(config, "NEWS_API_BASE_URL", "NEWS_API_URL", "api_base_url")
    if not api_url:
        warnings.append("Missing API base URL")
    elif api_url != EXPECTED_API_URL:
        warnings.append("Non-standard API base URL")

    db_path = _first_non_null(config, "DATABASE_PATH", "database_path")
    if db_path and db_path != EXPECTED_DB_PATH:
        warnings.append("Non-standard database path")
    elif not db_path:
        warnings.append("Missing database path")

    threshold = _first_non_null(config, "RELEVANCE_THRESHOLD", "relevance_threshold")
    try:
        if threshold is None:
            warnings.append("Missing relevance threshold")
        else:
            threshold_val = float(threshold)
            if not 0 <= threshold_val <= 1:
                warnings.append("Relevance threshold should be between 0 and 1")
            elif threshold_val < EXPECTED_THRESHOLD:
                warnings.append("Relevance threshold below recommended 0.7")
    except (TypeError, ValueError):
        warnings.append("Relevance threshold is not a number")

    rate_limit = _first_non_null(
        config, "rate_limit_requests_per_minute", "OPENAI_REQUESTS_PER_MINUTE"
    )
    if rate_limit is not None:
        try:
            if int(rate_limit) != 30:
                warnings.append("Rate limit differs from recommended 30 req/min")
        except (TypeError, ValueError):
            warnings.append("Rate limit should be an integer")

    return warnings

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
        salt_file = Path(self.keys_path + ".salt")
        legacy_key_file = Path(self.keys_path + ".key")

        if legacy_key_file.exists():
            try:
                legacy_key_file.unlink()
                logger.info("Removed legacy encryption key file at %s", legacy_key_file)
            except OSError:
                logger.warning("Could not remove legacy key file at %s", legacy_key_file)
 
        # If salt already exists, derive a deterministic key for this machine.
        # We intentionally do not persist the derived key on disk.
        if salt_file.exists():
            salt = salt_file.read_bytes()
            return self._derive_encryption_key(salt)
        
        # Generate new key with random salt

        # Generate a random salt
        salt = os.urandom(16)
        salt_file.write_bytes(salt)

        # Restrict file permissions when possible.
        try:
            os.chmod(salt_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.debug("Could not set strict permissions on %s", salt_file)

        return self._derive_encryption_key(salt)

    def _derive_encryption_key(self, salt: bytes) -> bytes:
        """Derive a stable encryption key from machine-bound metadata and optional secret."""
        # Use machine-specific information as a base for the password
        # This isn't perfect security but better than a hardcoded password
        try:
            nodename = os.uname().nodename
        except AttributeError:
            nodename = platform.node()

        if not nodename:
            nodename = hex(uuid.getnode())

        machine_id = hashlib.sha256(nodename.encode()).hexdigest()

        # Optional hardening hook for deployments.
        # If this is set, encrypted key files become unreadable without the secret.
        extra_secret = os.getenv("NEWS_SCRAPER_MASTER_KEY", "")
        password_material = f"{machine_id}:{extra_secret}".encode()
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password_material))

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
        
        # Load from environment variables with type conversion. Environment values are
        # treated as highest-precedence and merged last.
        type_map = {
            "NEWS_API_DAILY_LIMIT": int,
            "NEWS_API_REQUESTS_PER_SECOND": int,
            "OPENAI_REQUESTS_PER_MINUTE": int,
            "BATCH_SIZE": int,
            "RELEVANCE_THRESHOLD": float,
            "NEWS_API_PAGE_LIMIT": int,
            "FETCH_MAX_PAGES_PER_QUERY": int,
            "NEWS_API_MIN_BODY_LENGTH": int,
            "NEWS_API_URL_FALLBACK_TIMEOUT_SECONDS": int,
            "NEWS_API_URL_FALLBACK_MAX_CONCURRENCY": int,
            "RAW_ARTICLE_INSERT_BATCH_SIZE": int,
            "PRELLM_MIN_CONTENT_CHARS": int,
            "PRELLM_MAX_CONTENT_CHARS": int,
            "PRELLM_MIN_QUERY_TOKEN_OVERLAP": int,
            "PRELLM_TOP_K_PER_TERM": int,
            "QUERY_EXPANSION_VARIANTS_PER_TERM": int,
            "QUERY_EXPANSION_MAX_TOTAL_QUERIES": int,
            "REQUEST_BUDGET_PER_RUN": int,
        }
        bool_keys = {
            "NEWS_API_ENABLE_URL_FALLBACK",
            "PRELLM_ENABLE_FILTERING",
            "PRELLM_REQUIRE_INCIDENT_SIGNAL",
            "PRELLM_DEDUP_BY_URL",
            "PRELLM_DEDUP_BY_TITLE",
            "PRELLM_STAGE3_ENABLED",
            "PRELLM_LOG_DROPS",
            "PRELLM_ENABLE_LLM_GUARDRAIL",
            "QUERY_EXPANSION_ENABLED",
            "QUERY_EXPANSION_USE_AI",
        }
        
        env_config = {}
        for key in DEFAULT_CONFIG:
            env_value = os.getenv(f"NEWS_SCRAPER_{key}")
            if env_value:
                try:
                    if key in type_map:
                        env_config[key] = type_map[key](env_value)
                    elif key in bool_keys:
                        env_config[key] = str(env_value).strip().lower() in {"1", "true", "yes", "on"}
                    else:
                        env_config[key] = env_value
                except (ValueError, TypeError) as e:
                    logger.error(f"Error converting environment variable {key}: {e}")
                    env_config[key] = DEFAULT_CONFIG[key]

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

        # Load encrypted API keys.
        config.update(self._load_api_keys())

        # Environment has final precedence.
        config.update(env_config)

        # Fill in any missing values from defaults
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value

        # Warn if user config diverges from the template defaults
        self._warn_if_diverged(config)

        return config

    def _load_template_defaults(self) -> Dict[str, Any]:
        """Load template values for comparison; safe no-op if missing/invalid."""
        try:
            template_path = Path(self.config_path).with_name("config.template.json")
            if not template_path.exists():
                return {}
            with open(template_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read config template for comparison: {e}")
            return {}

    def _is_simplified_template(self, template: Dict[str, Any]) -> bool:
        """
        Detect the simplified template schema used for onboarding documentation.
        """
        expected_keys = {
            "api_base_url",
            "api_key_env_var",
            "database_path",
            "relevance_threshold",
            "rate_limit_requests_per_minute",
        }
        return set(template.keys()).issubset(expected_keys)

    def _warn_if_diverged(self, config: Dict[str, Any]) -> None:
        """
        Warn at startup if the active config differs from the template defaults.
        API keys are excluded from comparison.
        """
        template = self._load_template_defaults()
        if not template:
            return

        if self._is_simplified_template(template):
            return

        ignore_keys = {"NEWS_API_KEY", "OPENAI_API_KEY"}
        diffs = []

        for key, template_value in template.items():
            if key in ignore_keys:
                continue
            if key not in config:
                diffs.append(f"{key}=<missing> (template: {template_value!r})")
            else:
                if config[key] != template_value:
                    diffs.append(f"{key}={config[key]!r} (template: {template_value!r})")

        extra_keys = [k for k in config.keys() if k not in template and k not in ignore_keys]
        if extra_keys:
            diffs.append(f"extra keys present: {', '.join(sorted(extra_keys))}")

        if diffs:
            logger.warning(
                "Active config differs from config.template.json: %s",
                "; ".join(diffs),
            )

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
            sensitive_keys = {"NEWS_API_KEY", "OPENAI_API_KEY"}
            safe_config = {k: v for k, v in config.items() if k not in sensitive_keys}
            with open(self.config_path, 'w', encoding="utf-8") as f:
                json.dump(safe_config, f, indent=4)
                
            # Update running config
            if hasattr(self, "config") and isinstance(self.config, dict):
                self.config.update(config)
            
            logger.info("Config and API keys saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.config.get(key, default)

    def get_context_message(self) -> Dict[str, str]:
        """Get LLM context message with explicit file-over-default precedence."""
        context_message = self.config.get("CHATGPT_CONTEXT_MESSAGE")
        if isinstance(context_message, dict):
            role = context_message.get("role") or DEFAULT_CONTEXT_MESSAGE["role"]
            content = context_message.get("content")
            if isinstance(content, str) and content.strip():
                return {"role": role, "content": content}
        return DEFAULT_CONTEXT_MESSAGE

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

            news_page_limit = int(self.config.get("NEWS_API_PAGE_LIMIT", 50))
            if news_page_limit <= 0:
                logger.error("NEWS_API_PAGE_LIMIT must be positive")
                return False
            max_pages_per_query = int(self.config.get("FETCH_MAX_PAGES_PER_QUERY", 5))
            if max_pages_per_query <= 0:
                logger.error("FETCH_MAX_PAGES_PER_QUERY must be positive")
                return False

            news_min_body_length = int(self.config.get("NEWS_API_MIN_BODY_LENGTH", 0))
            if news_min_body_length < 0:
                logger.error("NEWS_API_MIN_BODY_LENGTH must be >= 0")
                return False

            if int(self.config.get("NEWS_API_URL_FALLBACK_TIMEOUT_SECONDS", 0)) <= 0:
                logger.error("NEWS_API_URL_FALLBACK_TIMEOUT_SECONDS must be positive")
                return False

            if int(self.config.get("NEWS_API_URL_FALLBACK_MAX_CONCURRENCY", 0)) < 0:
                logger.error("NEWS_API_URL_FALLBACK_MAX_CONCURRENCY must be >= 0")
                return False

            if int(self.config.get("RAW_ARTICLE_INSERT_BATCH_SIZE", 0)) <= 0:
                logger.error("RAW_ARTICLE_INSERT_BATCH_SIZE must be positive")
                return False

            if int(self.config.get("PRELLM_MIN_CONTENT_CHARS", 0)) < 0:
                logger.error("PRELLM_MIN_CONTENT_CHARS must be >= 0")
                return False

            if int(self.config.get("PRELLM_MAX_CONTENT_CHARS", 0)) <= 0:
                logger.error("PRELLM_MAX_CONTENT_CHARS must be > 0")
                return False

            if int(self.config.get("PRELLM_MIN_CONTENT_CHARS", 0)) > int(
                self.config.get("PRELLM_MAX_CONTENT_CHARS", 0)
            ):
                logger.error("PRELLM_MIN_CONTENT_CHARS must be <= PRELLM_MAX_CONTENT_CHARS")
                return False

            if int(self.config.get("PRELLM_MIN_QUERY_TOKEN_OVERLAP", 0)) < 0:
                logger.error("PRELLM_MIN_QUERY_TOKEN_OVERLAP must be >= 0")
                return False

            if int(self.config.get("PRELLM_TOP_K_PER_TERM", 0)) < 0:
                logger.error("PRELLM_TOP_K_PER_TERM must be >= 0")
                return False
            preset = str(self.config.get("PRELLM_FILTER_PRESET", "more_permissive")).strip().lower()
            if preset not in {"more_permissive", "medium", "most_aggressive"}:
                logger.error("PRELLM_FILTER_PRESET must be one of: more_permissive, medium, most_aggressive")
                return False

            topic_overrides = self.config.get("PRELLM_TOPIC_OVERRIDES", {})
            if topic_overrides is None:
                topic_overrides = {}
            if not isinstance(topic_overrides, dict):
                logger.error("PRELLM_TOPIC_OVERRIDES must be a dictionary")
                return False
            for topic_name, override in topic_overrides.items():
                if not isinstance(topic_name, str) or not topic_name.strip():
                    logger.error("PRELLM_TOPIC_OVERRIDES keys must be non-empty strings")
                    return False
                if not isinstance(override, dict):
                    logger.error("Each PRELLM topic override must be a dictionary")
                    return False
                min_chars = int(override.get("min_content_chars", self.config.get("PRELLM_MIN_CONTENT_CHARS", 0)))
                max_chars = int(override.get("max_content_chars", self.config.get("PRELLM_MAX_CONTENT_CHARS", 0)))
                min_overlap = int(
                    override.get("min_query_token_overlap", self.config.get("PRELLM_MIN_QUERY_TOKEN_OVERLAP", 0))
                )
                top_k = int(override.get("top_k_per_term", self.config.get("PRELLM_TOP_K_PER_TERM", 0)))
                if min_chars < 0 or max_chars <= 0 or min_chars > max_chars:
                    logger.error("Invalid min/max content chars in PRELLM topic override for '%s'", topic_name)
                    return False
                if min_overlap < 0:
                    logger.error("min_query_token_overlap must be >= 0 in PRELLM topic override for '%s'", topic_name)
                    return False
                if top_k < 0:
                    logger.error("top_k_per_term must be >= 0 in PRELLM topic override for '%s'", topic_name)
                    return False
            if int(self.config.get("QUERY_EXPANSION_VARIANTS_PER_TERM", 0)) < 0:
                logger.error("QUERY_EXPANSION_VARIANTS_PER_TERM must be >= 0")
                return False
            if int(self.config.get("QUERY_EXPANSION_MAX_TOTAL_QUERIES", 0)) < 0:
                logger.error("QUERY_EXPANSION_MAX_TOTAL_QUERIES must be >= 0")
                return False
            if int(self.config.get("REQUEST_BUDGET_PER_RUN", 0)) <= 0:
                logger.error("REQUEST_BUDGET_PER_RUN must be positive")
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
