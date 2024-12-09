"""src/validation.py"""
import re
import html
import bleach
from datetime import datetime
from typing import Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse

class ArticleValidator:
    def __init__(self):
        self.allowed_tags = ['p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 'ul', 'ol', 'li']
        self.url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        
        # Unescape HTML entities
        text = html.unescape(text)
        
        # Strip HTML tags except allowed ones
        text = bleach.clean(text, tags=self.allowed_tags, strip=True)
        
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        return text

    def validate_url(self, url: str) -> bool:
        if not url:
            return False
        
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc and self.url_pattern.match(url))

    def validate_date(self, date_str: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

    def clean_article(self, article: Dict) -> Optional[Dict]:
        try:
            # Clean and validate required fields
            title = self.clean_text(article.get('title'))
            content = self.clean_text(article.get('content'))
            url = article.get('url')
            published_at = article.get('published_at')

            if not all([title, content, url]):
                return None

            if not self.validate_url(url):
                return None

            if published_at:
                published_at = self.validate_date(published_at)
                if not published_at:
                    return None

            return {
                'title': title,
                'content': content,
                'url': url,
                'published_at': published_at,
                'source_name': self.clean_text(article.get('source_name', '')),
                'url_to_image': url if self.validate_url(article.get('url_to_image')) else None
            }

        except Exception as e:
            logging.error(f"Error validating article: {e}")
            return None