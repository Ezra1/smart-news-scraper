import sys
import os

# Add the root directory to the Python path to make `src` available
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import ArticleManager  # Import after adding to the path

# Sample data to test the function
search_term_id = 1
title = "Sample Article Title"
content = "This is the content of the article."
source = "Example News Source"
url = "https://example.com/sample-article"
url_to_image = "https://example.com/image.jpg"
published_at = "2024-06-29T09:00:00Z"

# Create an instance of ArticleManager if insert_raw_article is not a classmethod
article_manager = ArticleManager()

# Insert the article using the instance of ArticleManager
article_id = article_manager.insert_raw_article(
    search_term_id, title, content, source, url, url_to_image, published_at
)
print(f"Inserted article with ID: {article_id}")