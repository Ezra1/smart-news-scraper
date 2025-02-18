import numpy as np
from typing import List, Dict, Optional
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.logger_config import setup_logging
logger = setup_logging(__name__)

class ArticleDeduplicator:
    def __init__(self, similarity_threshold: float = 0.85):
        """
        Initialize the deduplicator with a similarity threshold.
        Uses TF-IDF vectorization for efficient duplicate detection.
        
        Args:
            similarity_threshold (float): Threshold for considering articles as duplicates
        """
        if not 0 <= similarity_threshold <= 1:
            logger.warning(f"Invalid similarity threshold {similarity_threshold}. Using default 0.85")
            similarity_threshold = 0.85
            
        self.threshold = similarity_threshold
        self.vectorizer = TfidfVectorizer(stop_words="english")

    def find_exact_duplicates(self, articles: List[Dict]) -> List[int]:
        """
        Identify exact duplicate articles based on title and URL.
        
        Args:
            articles (List[Dict]): List of article dictionaries
            
        Returns:
            List[int]: List of duplicate article IDs
        """
        if not articles:
            logger.info("No articles provided for exact duplicate detection")
            return []

        try:
            duplicates = set()
            seen = {}

            for article in articles:
                if not isinstance(article, dict):
                    logger.error(f"Invalid article format: {type(article)}")
                    continue
                    
                try:
                    title = article.get("title", "").strip().lower()
                    url = article.get("url", "").strip().lower()
                    article_id = article.get("id")
                    
                    if not all([title, url, article_id]):
                        logger.warning(f"Missing required fields in article {article_id}")
                        continue
                        
                    key = (title, url)
                    if key in seen:
                        duplicates.add(article_id)
                    else:
                        seen[key] = article_id
                except AttributeError as e:
                    logger.error(f"Error processing article: {e}")
                    continue

            return list(duplicates)

        except Exception as e:
            logger.error(f"Exact duplicate detection failed: {e}")
            return []

    def find_near_duplicates(self, articles: List[Dict]) -> List[int]:
        """
        Identify near-duplicate articles using TF-IDF vectorization and cosine similarity.
        
        Args:
            articles (List[Dict]): List of article dictionaries
            
        Returns:
            List[int]: List of near-duplicate article IDs
        """
        if not articles:
            return []

        try:
            contents = [article.get("content", "") for article in articles]
            if not any(contents):
                logger.warning("No article contents to process")
                return []

            article_ids = [article.get("id") for article in articles]
            if not all(article_ids):
                logger.error("Missing article IDs")
                return []

            # Compute TF-IDF vectors
            try:
                tfidf_matrix = self.vectorizer.fit_transform(contents)
            except ValueError as e:
                logger.error(f"TF-IDF vectorization failed: {e}")
                return []

            try:
                similarity_matrix = cosine_similarity(tfidf_matrix)
            except ValueError as e:
                logger.error(f"Similarity computation failed: {e}")
                return []

            duplicate_ids = set()

            for i in range(len(articles)):
                for j in range(i + 1, len(articles)):
                    try:
                        similarity_score = similarity_matrix[i, j]
                        if similarity_score >= self.threshold:
                            duplicate_ids.add(article_ids[j])
                    except IndexError as e:
                        logger.error(f"Error accessing similarity matrix: {e}")
                        continue

            return list(duplicate_ids)

        except Exception as e:
            logger.error(f"Near-duplicate detection failed: {e}")
            return []

    def remove_duplicates(self, articles: List[Dict]) -> List[Dict]:
        """
        Removes duplicate articles from the list based on exact and near-duplicate detection.
        
        Args:
            articles (List[Dict]): List of article dictionaries
            
        Returns:
            List[Dict]: List of unique articles
        """
        if not articles:
            logger.info("No articles provided for deduplication")
            return []

        try:
            initial_count = len(articles)
            exact_duplicates = self.find_exact_duplicates(articles)
            near_duplicates = self.find_near_duplicates(articles)

            duplicate_ids = set(exact_duplicates + near_duplicates)
            filtered_articles = [
                article for article in articles 
                if article.get("id") not in duplicate_ids
            ]

            removed_count = initial_count - len(filtered_articles)
            logger.info(f"Removed {removed_count} duplicate articles "
                       f"({len(exact_duplicates)} exact, {len(near_duplicates)} near)")

            return filtered_articles

        except Exception as e:
            logger.error(f"Article deduplication failed: {e}")
            return articles  # Return original articles if deduplication fails

if __name__ == "__main__":
    # Example Usage with error handling
    try:
        test_articles = [
            {"id": 1, "title": "Breaking News", "content": "Important news content", 
             "url": "https://example.com/news1"},
            {"id": 2, "title": "Breaking News", "content": "Important news content", 
             "url": "https://example.com/news1"},
            {"id": 3, "title": "World Update", "content": "Some different content", 
             "url": "https://example.com/news2"},
            {"id": 4, "title": "Breaking News!", "content": "Important news content.", 
             "url": "https://example.com/news3"},
        ]

        deduplicator = ArticleDeduplicator()
        unique_articles = deduplicator.remove_duplicates(test_articles)

        print(f"Initial article count: {len(test_articles)}")
        print(f"Unique articles count: {len(unique_articles)}")
        
    except Exception as e:
        logger.error(f"Error in deduplication example: {e}")
        print("Deduplication process failed. Check logs for details.")