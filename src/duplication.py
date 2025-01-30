import logging
import numpy as np
from typing import List, Dict
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class ArticleDeduplicator:
    def __init__(self, similarity_threshold: float = 0.85):
        """
        Initialize the deduplicator with a similarity threshold.
        Uses TF-IDF vectorization for efficient duplicate detection.
        """
        self.threshold = similarity_threshold
        self.vectorizer = TfidfVectorizer(stop_words="english")

    def find_exact_duplicates(self, articles: List[Dict]) -> List[int]:
        """
        Identify exact duplicate articles based on title and URL.
        Returns a list of duplicate article IDs.
        """
        duplicates = set()
        seen = {}

        for article in articles:
            key = (article["title"].strip().lower(), article["url"].strip().lower())
            if key in seen:
                duplicates.add(article["id"])
            else:
                seen[key] = article["id"]

        return list(duplicates)

    def find_near_duplicates(self, articles: List[Dict]) -> List[int]:
        """
        Identify near-duplicate articles using TF-IDF vectorization and cosine similarity.
        Returns a list of duplicate article IDs.
        """
        if len(articles) < 2:
            return []

        try:
            contents = [article["content"] for article in articles]
            article_ids = [article["id"] for article in articles]

            # Compute TF-IDF vectors
            tfidf_matrix = self.vectorizer.fit_transform(contents)
            similarity_matrix = cosine_similarity(tfidf_matrix)

            duplicate_ids = set()

            for i in range(len(articles)):
                for j in range(i + 1, len(articles)):
                    similarity_score = similarity_matrix[i, j]
                    if similarity_score >= self.threshold:
                        duplicate_ids.add(article_ids[j])

            return list(duplicate_ids)

        except Exception as e:
            logging.error(f"❌ Error finding near duplicates: {e}")
            return []

    def remove_duplicates(self, articles: List[Dict]) -> List[Dict]:
        """
        Removes duplicate articles from the list based on exact and near-duplicate detection.
        Returns a list of unique articles.
        """
        exact_duplicates = self.find_exact_duplicates(articles)
        near_duplicates = self.find_near_duplicates(articles)

        duplicate_ids = set(exact_duplicates + near_duplicates)
        filtered_articles = [article for article in articles if article["id"] not in duplicate_ids]

        logging.info(f"✅ Removed {len(duplicate_ids)} duplicate articles.")
        return filtered_articles

if __name__ == "__main__":
    # Example Usage
    test_articles = [
        {"id": 1, "title": "Breaking News", "content": "Important news content", "url": "https://example.com/news1"},
        {"id": 2, "title": "Breaking News", "content": "Important news content", "url": "https://example.com/news1"},
        {"id": 3, "title": "World Update", "content": "Some different content", "url": "https://example.com/news2"},
        {"id": 4, "title": "Breaking News!", "content": "Important news content.", "url": "https://example.com/news3"},
    ]

    deduplicator = ArticleDeduplicator()
    unique_articles = deduplicator.remove_duplicates(test_articles)

    print(f"Unique Articles Count: {len(unique_articles)}")
