import re
import bleach
from dateutil import parser
from datetime import datetime, timezone
from typing import Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from src.logger_config import setup_logging
logger = setup_logging(__name__)

class ArticleValidator:
    # Tight HTML whitelist and length limits to reduce XSS/oversize payloads
    MAX_TITLE_LENGTH = 500
    MAX_CONTENT_LENGTH = 100_000
    MAX_RAW_TITLE_LENGTH = 4_000
    MAX_RAW_CONTENT_LENGTH = 120_000

    def __init__(self):
        # Define allowed HTML elements with specific attributes (no images/links/classes)
        self.allowed_tags = ['p', 'br', 'b', 'i', 'u', 'strong', 'em']
        
        # Define allowed attributes for specific tags
        self.allowed_attributes = {}
        
        # Define allowed URL schemes
        self.allowed_protocols = ['http', 'https']
        
        # Improved URL pattern with stricter validation
        self.url_pattern = re.compile(
            r'^https?://(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+' \
            r'(?:[A-Z]{2,6}|[A-Z0-9-]{2,})\b(?:[/?][-\w/.?=&#%]*)?$',
            re.IGNORECASE
        )

    def clean_text(self, text: str) -> str:
        """
        Sanitize and clean text with enhanced security measures.
        
        Args:
            text (str): Input text to be sanitized
            
        Returns:
            str: Sanitized text with dangerous content removed
        """
        if not text:
            return ""
        if not isinstance(text, str):
            text = str(text)
        # Fast path: plain text does not need HTML parser passes.
        if "<" not in text and ">" not in text:
            return " ".join(text.split())
            
        try:
            # Create custom cleaner with simplified settings
            cleaner = bleach.Cleaner(
                tags=self.allowed_tags,
                attributes=self.allowed_attributes,
                strip=True,
                strip_comments=True
            )
            
            # Clean the text
            text = cleaner.clean(text)
            
            # Additional sanitization steps
            soup = BeautifulSoup(text, 'html.parser')
            
            # Remove empty tags
            for tag in soup.find_all():
                if len(tag.get_text(strip=True)) == 0 and tag.name != 'br':
                    tag.decompose()
            
            # Convert soup back to string and normalize whitespace
            text = str(soup)
            text = ' '.join(text.split())
            
            return text
            
        except Exception as e:
            logger.error(f"Text cleaning failed: {e}")
            return ""

    @staticmethod
    def _cap_raw_text(value: object, max_length: int) -> str:
        if value is None:
            return ""
        text = value if isinstance(value, str) else str(value)
        if max_length <= 0:
            return ""
        if len(text) <= max_length:
            return text
        return text[:max_length]

    def validate_url(self, url: str) -> bool:
        """
        Validate URL with enhanced security checks.
        
        Args:
            url (str): URL to validate
            
        Returns:
            bool: True if URL is valid and safe, False otherwise
        """
        if not url:
            return False
            
        try:
            # Parse URL
            parsed = urlparse(url)
            
            # Basic validation
            if not all([parsed.scheme, parsed.netloc]):
                return False
                
            # Check against regex pattern
            if not self.url_pattern.match(url):
                return False
                
            # Ensure scheme is http or https
            if parsed.scheme not in self.allowed_protocols:
                return False
                
            # Additional security checks
            if any(char in url for char in ['<', '>', '"', "'", ';', '{', '}']):
                return False
                
            # Ensure URL does not contain dangerous characters in query or fragment
            if any(char in parsed.query + parsed.fragment for char in ['<', '>', '"', "'", ';', '{', '}']):
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"URL validation failed for '{url}': {e}")
            return False

    def validate_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse and validate date string with timezone awareness.
        
        Args:
            date_str (str): Date string to validate
            
        Returns:
            Optional[datetime]: Parsed datetime object or None if invalid
        """
        if not date_str:
            return None
            
        try:
            # Parse the date string into a timezone-aware datetime
            parsed_date = parser.parse(date_str)
            if parsed_date.tzinfo is None:
                # If the parsed date has no timezone, assume UTC
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            
            # Get current time in UTC
            current_date = datetime.now(timezone.utc)
            
            # Ensure reasonable past date (e.g., not before 2000)
            min_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
            
            if parsed_date > current_date:
                logger.warning(f"Future date detected: {date_str}")
                return None
                
            if parsed_date < min_date:
                logger.warning(f"Date too old: {date_str}")
                return None
                
            return parsed_date
            
        except (ValueError, TypeError) as e:
            logger.error(f"Date parsing failed for '{date_str}': {e}")
            return None

    def clean_article(self, article: Dict) -> Optional[Dict]:
        """
        Clean and validate article with enhanced security measures.
        
        Args:
            article (Dict): Article data to validate and clean
            
        Returns:
            Optional[Dict]: Cleaned article data or None if validation fails
        """
        if not isinstance(article, dict):
            logger.error("clean_article expected dict, got %s", type(article).__name__)
            return None

        try:
            # Validate required fields
            required_fields = {'title', 'content', 'url'}
            if not all(field in article for field in required_fields):
                logger.error(f"Missing required fields: {required_fields - set(article.keys())}")
                return None

            # Validate URL early to avoid expensive cleaning work on dropped rows.
            url = article.get("url", "")
            if not self.validate_url(url):
                logger.error(f"Invalid URL: {url}")
                return None

            # Clean and validate individual fields
            raw_title = self._cap_raw_text(article.get("title", ""), self.MAX_RAW_TITLE_LENGTH)
            raw_content = self._cap_raw_text(article.get("content", ""), self.MAX_RAW_CONTENT_LENGTH)

            title = self.clean_text(raw_title)
            content = self.clean_text(raw_content)
            if len(title) > self.MAX_TITLE_LENGTH:
                title = title[:self.MAX_TITLE_LENGTH]
            if len(content) > self.MAX_CONTENT_LENGTH:
                content = content[:self.MAX_CONTENT_LENGTH]
            published_at = article.get('published_at', '')
            url_to_image = article.get('url_to_image', '')
            if url_to_image and not self.validate_url(url_to_image):
                url_to_image = None
            
            # Validate required fields
            if not all([title, content, url]):
                logger.error("Required fields empty after cleaning")
                return None
                
            # Validate and parse date
            if published_at:
                published_at = self.validate_date(published_at)
                if not published_at:
                    logger.error(f"Invalid published date: {article.get('published_at')}")
                    return None
                    
            # Keep optional enrichment metadata for downstream relevance/explainer steps.
            passthrough_fields = [
                "source",
                "description",
                "snippet",
                "search_term_id",
                "query_term",
                "query_language",
                "root_term",
                "incident_level",
                "event_uri",
                "concepts",
                "categories",
                "location",
                "extracted_dates",
                "incident_sentence",
                "event_type_uri",
                "source_rank_percentile",
                "full_text",
                "body_source",
                "url_fallback_status",
                "image_url",
            ]

            # Construct cleaned article
            cleaned_article = {
                'title': title,
                'content': content,
                'url': url,
                'published_at': published_at,
                'source_name': self.clean_text(article.get('source_name', '')),
                'url_to_image': url_to_image,
            }

            for field in passthrough_fields:
                if field in article:
                    cleaned_article[field] = article.get(field)
            
            logger.info(f"Article cleaned successfully: {title}")
            return cleaned_article
            
        except Exception as e:
            logger.error(f"Article cleaning failed: {e}")
            return None

if __name__ == "__main__":
    # Example usage with enhanced security
    validator = ArticleValidator()
    
    sample_article = {
        'title': '<p>Sample News Article</p>',
        'content': '<p>This is <script>alert("test");</script><b>important</b> content!</p>',
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