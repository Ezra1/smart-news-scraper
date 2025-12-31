from typing import Optional

from openai import OpenAI

from src.config import ConfigManager
from src.logger_config import setup_logging

logger = setup_logging(__name__)


def get_client(api_key: Optional[str] = None) -> OpenAI:
    """
    Create an OpenAI client using a provided API key or the configured default.
    """
    key = api_key or ConfigManager().get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is required to create an OpenAI client.")

    logger.debug("Creating OpenAI client")
    return OpenAI(api_key=key)


__all__ = ["get_client"]

