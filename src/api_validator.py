import aiohttp
import asyncio
from openai import OpenAI
from src.logger_config import setup_logging

logger = setup_logging(__name__)

async def validate_news_api_key(api_key: str) -> bool:
    """Validate News API key with a test request."""
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "test",
        "pageSize": 1,
        "apiKey": api_key
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    logger.info("News API key validated successfully")
                    return True
                elif response.status == 401:
                    logger.error("Invalid News API key")
                    return False
                else:
                    logger.error(f"News API validation failed with status {response.status}")
                    return False
    except Exception as e:
        logger.error(f"News API validation error: {e}")
        return False

def validate_openai_api_key(api_key: str) -> bool:
    """Validate OpenAI API key with a test request."""
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
