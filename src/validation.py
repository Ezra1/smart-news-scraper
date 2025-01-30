import re
import html
import bleach
import logging
from dateutil import parser
from datetime import datetime
from typing import Dict, Optional, Set
from bs4 import BeautifulSoup, Comment
from urllib.parse import urlparse, urljoin

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ArticleValidator:
    def __init__(self):
        # Define allowed HTML elements with specific attributes
        self.allowed_tags = [
            'p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 
            'ul', 'ol', 'li', 'a', 'blockquote'
        ]
        
        # Define allowed attributes for specific tags
        self.allowed_attributes = {
            '*': ['class'],  # Allow class attribute on all elements
            'a': ['href', 'title', 'rel'],  # Specific attributes for links
            'img': ['alt', 'title']  # Basic image attributes if needed
        }
        
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
            
        try:
            # Unescape HTML entities first
            text = html.unescape(text)
            
            # Create custom cleaner with strict security settings
            cleaner = bleach.Cleaner(
                tags=self.allowed_tags,
                attributes=self.allowed_attributes,
                protocols=self.allowed_protocols,
                strip=True,
                filters=[
                    # Custom filter for href attributes
                    lambda tag, name, value: value 
                    if name == 'href' and value and 
                    value.startswith(('http:', 'https:'))
                    else None
                ]
            )
            
            # Clean the text
            text = cleaner.clean(text)
            
            # Additional sanitization steps
            soup = BeautifulSoup(text, 'html.parser')
            
            # Remove comments
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()
                
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
        Parse and validate date string with additional checks.
        
        Args:
            date_str (str): Date string to validate
            
        Returns:
            Optional[datetime]: Parsed datetime object or None if invalid
        """
        if not date_str:
            return None
            
        try:
            parsed_date = parser.parse(date_str)
            
            # Additional validation checks
            current_date = datetime.now()
            if parsed_date > current_date:
                logger.warning(f"Future date detected: {date_str}")
                return None
                
            # Ensure reasonable past date (e.g., not before 2000)
            if parsed_date.year < 2000:
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
        try:
            # Validate required fields
            required_fields = {'title', 'content', 'url'}
            if not all(field in article for field in required_fields):
                logger.error(f"Missing required fields: {required_fields - set(article.keys())}")
                return None
                
            # Clean and validate individual fields
            title = self.clean_text(article.get('title', ''))
            content = self.clean_text(article.get('content', ''))
            url = article.get('url', '')
            published_at = article.get('published_at', '')
            url_to_image = article.get('url_to_image', '')
            if url_to_image and not self.validate_url(url_to_image):
                url_to_image = None
            
            # Validate required fields
            if not all([title, content, url]):
                logger.error("Required fields empty after cleaning")
                return None
                
            if not self.validate_url(url):
                logger.error(f"Invalid URL: {url}")
                return None
                
            # Validate and parse date
            if published_at:
                published_at = self.validate_date(published_at)
                if not published_at:
                    logger.error(f"Invalid published date: {article.get('published_at')}")
                    return None
                    
            # Construct cleaned article
            cleaned_article = {
                'title': title,
                'content': content,
                'url': url,
                'published_at': published_at,
                'source_name': self.clean_text(article.get('source_name', '')),
                'url_to_image': url_to_image
            }
            
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