import sys
import os

# Add the root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import insert_raw_article

# Sample data to test the function
search_term_id = 1
title = "Sample Article Title"
content = "This is the content of the article."
source = "Example News Source"
url = "https://example.com/sample-article"
urlToImage = "https://example.com/image.jpg"
published_at = "2024-06-29T09:00:00Z"

# Insert the article
article_id = insert_raw_article(search_term_id, title, content, source, url, urlToImage, published_at)
print(f"Inserted article with ID: {article_id}")