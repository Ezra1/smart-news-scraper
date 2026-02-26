import re
from typing import Tuple

import aiohttp
from bs4 import BeautifulSoup

from src.logger_config import setup_logging

logger = setup_logging(__name__)


async def fetch_readable_text(
    url: str,
    timeout_seconds: int = 15,
    min_length: int = 400,
) -> Tuple[str, str]:
    """Fetch an article URL and extract readable text.

    Returns:
        tuple(text, status) where status is one of:
        - fetched
        - too_short
        - http_error
        - timeout
        - parse_error
        - empty
    """
    if not url:
        return "", "empty"

    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=7)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return "", "http_error"
                html_text = await response.text(errors="ignore")
    except aiohttp.ClientError as e:
        logger.warning("URL fallback fetch failed for %s: %s", url, e)
        return "", "http_error"
    except TimeoutError:
        return "", "timeout"

    try:
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer"]):
            tag.decompose()

        paragraph_text = " ".join(
            p.get_text(" ", strip=True)
            for p in soup.find_all("p")
            if p.get_text(" ", strip=True)
        )
        text = paragraph_text or soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return "", "empty"
        if len(text) < min_length:
            return text, "too_short"
        return text, "fetched"
    except Exception as e:
        logger.warning("URL fallback parse failed for %s: %s", url, e)
        return "", "parse_error"
