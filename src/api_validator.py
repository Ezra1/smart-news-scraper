import aiohttp
import asyncio
from openai import OpenAI
from src.logger_config import setup_logging

logger = setup_logging(__name__)

def _has_valid_api_key(api_key: str, provider: str) -> bool:
    """Validate a non-empty API key payload for validators."""
    if isinstance(api_key, str) and api_key.strip():
        return True
    logger.error("Cannot validate empty %s API key", provider)
    return False

async def validate_news_api_key(api_key: str) -> bool:
    """Validate TheNewsAPI token with a test request."""
    if not _has_valid_api_key(api_key, "TheNewsAPI"):
        return False

    url = "https://api.thenewsapi.com/v1/news/top"
    params = {"api_token": api_key, "limit": 1, "language": "en"}
    
    try:
        # trust_env=True allows corporate/VPN proxy env vars (HTTPS_PROXY, etc.)
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    logger.info("TheNewsAPI token validated successfully")
                    return True
                elif response.status == 401:
                    logger.error("Invalid TheNewsAPI token (401)")
                    return False
                elif response.status in (402, 429):
                    # 402 = usage limit reached, 429 = rate limit reached
                    body = await response.text()
                    logger.warning(
                        "TheNewsAPI token appears valid but limits are reached "
                        f"(status {response.status}): {body}"
                    )
                    return True
                else:
                    body = await response.text()
                    logger.error(
                        f"TheNewsAPI validation failed with status {response.status}. "
                        f"Response: {body}"
                    )
                    return False
    except asyncio.TimeoutError:
        logger.error("TheNewsAPI validation timed out")
        return False
    except Exception as e:
        logger.error(f"TheNewsAPI validation error: {e}")
        return False

def validate_openai_api_key(api_key: str) -> bool:
    """Validate OpenAI API key with a test request."""
    if not _has_valid_api_key(api_key, "OpenAI"):
        return False

    try:
        client = OpenAI(api_key=api_key)
        # Make a minimal test request
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5
        )
        logger.info("OpenAI API key validated successfully")
        return True
    except Exception as e:
        logger.error(f"OpenAI API validation error: {e}")
        return False
