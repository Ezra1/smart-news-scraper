import re
import html
import bleach
import logging
from dateutil import parser
from datetime import datetime
from typing import Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ArticleValidator:
    def __init__(self):
        # Allow basic formatting tags
        self.allowed_tags = ['p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 'ul', 'ol', 'li', 'a', 'blockquote']
        # Improved URL pattern to accommodate various domains and subdomains
        self.url_pattern = re.compile(
            r'^https?://(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}|[A-Z0-9-]{2,})\b(?:[/?].*)?$', 
            re.IGNORECASE
        )

    def clean_text(self, text: str) -> str:
        """Sanitize and clean text by removing unwanted HTML elements."""
        if not text:
            return ""
        
        try:
            # Unescape HTML entities
            text = html.unescape(text)
            # Strip HTML tags except allowed ones
            text = bleach.clean(text, tags=self.allowed_tags, strip=True)
            # Remove extra whitespace
            text = ' '.join(text.split())
        except Exception as e:
            logger.error(f"❌ Error cleaning text: {e}")
            text = ""
        
        return text

    def validate_url(self, url: str) -> bool:
        """Check if the provided URL is valid based on regex pattern."""
        if not url:
            return False
        
        try:
            parsed = urlparse(url)
            is_valid = bool(parsed.scheme and parsed.netloc and self.url_pattern.match(url))
            if not is_valid:
                logger.warning(f"⚠️ Invalid URL detected: {url}")
            return is_valid
        except Exception as e:
            logger.error(f"❌ Error validating URL '{url}': {e}")
            return False

    def validate_date(self, date_str: str) -> Optional[datetime]:
        """Attempt to parse the date string into a datetime object."""
        try:
            return parser.parse(date_str)
        except (ValueError, TypeError) as e:
            logger.error(f"❌ Error parsing date '{date_str}': {e}")
            return None

    def clean_article(self, article: Dict) -> Optional[Dict]:
        """
        Clean and validate an article dictionary.
        Ensures required fields are present and valid.
        """
        try:
            # Clean and validate required fields
            title = self.clean_text(article.get('title', ''))
            content = self.clean_text(article.get('content', ''))
            url = article.get('url', '')
            published_at = article.get('published_at', '')

            # Required fields must be present and valid
            if not all([title, content, url]):
                logger.error(f"❌ Missing required article fields: {article}")
                return None

            if not self.validate_url(url):
                logger.error(f"❌ Invalid URL: {url}")
                return None

            if published_at:
                published_at = self.validate_date(published_at)
                if not published_at:
                    logger.error(f"❌ Invalid published date: {published_at}")
                    return None

            # Construct cleaned article object
            cleaned_article = {
                'title': title,
                'content': content,
                'url': url,
                'published_at': published_at,
                'source_name': self.clean_text(article.get('source_name', '')),
                'url_to_image': url if self.validate_url(article.get('url_to_image', '')) else None
            }

            logger.info(f"✅ Article '{title}' cleaned and validated successfully.")
            return cleaned_article

        except Exception as e:
            logger.error(f"❌ Error validating article: {e}")
            return None

if __name__ == "__main__":
    # Example usage
    validator = ArticleValidator()
    sample_article = {
        'title': 'Sample News Article',
        'content': '<p>This is <b>important</b> content!</p>',
        'url': 'https://example.com/news/sample',
        'published_at': '2025-01-01T12:00:00Z',
        'source_name': 'Example News',
        'url_to_image': 'https://example.com/images/sample.jpg'
    }

    cleaned_article = validator.clean_article(sample_article)
    if cleaned_article:
        print("Cleaned Article:", cleaned_article)
    else:
        print("Article validation failed.")
