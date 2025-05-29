import sys
import os

# Add the root directory to the Python path to access files in src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the necessary classes
from src.database_manager import DatabaseManager, ArticleManager

# Create an instance of DatabaseManager
db_manager = DatabaseManager()

# Create an instance of ArticleManager and pass the db_manager instance
article_manager = ArticleManager(db_manager)

# Update test article insertion
test_article = {
    'title': 'Sample Article Title',
    'content': 'This is the content of the article.',
    'source': {'name': 'Example News Source'},  # Use dict format for source
    'url': 'https://example.com/sample-article',
    'url_to_image': 'https://example.com/image.jpg',
    'published_at': '2024-06-29T09:00:00Z',
    'search_term_id': 1
}

# Insert the article
article_id = article_manager.insert_article(test_article)
print(f"Inserted article with ID: {article_id}")
