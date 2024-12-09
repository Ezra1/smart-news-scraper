from typing import List, Dict, Tuple
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

class ArticleDeduplicator:
    def __init__(self, similarity_threshold: float = 0.85):
        self.threshold = similarity_threshold
        self.vectorizer = TfidfVectorizer(stop_words='english')

    def find_duplicates(self, articles: List[Dict]) -> List[Tuple[int, int, float]]:
        texts = [f"{article['title']} {article['content']}" for article in articles]
        tfidf_matrix = self.vectorizer.fit_transform(texts)
        
        # Calculate similarity matrix
        similarities = cosine_similarity(tfidf_matrix)
        duplicates = []

        # Find pairs above threshold
        for i in range(len(articles)):
            for j in range(i + 1, len(articles)):
                if similarities[i][j] > self.threshold:
                    duplicates.append((
                        articles[i]['id'],
                        articles[j]['id'],
                        float(similarities[i][j])
                    ))

        return duplicates

    def remove_duplicates(self, articles: List[Dict]) -> List[Dict]:
        duplicates = self.find_duplicates(articles)
        to_remove = set()

        for id1, id2, _ in duplicates:
            # Keep the newer article
            article1 = next(a for a in articles if a['id'] == id1)
            article2 = next(a for a in articles if a['id'] == id2)
            
            if article1['published_at'] < article2['published_at']:
                to_remove.add(id1)
            else:
                to_remove.add(id2)

        return [a for a in articles if a['id'] not in to_remove]