from typing import Dict
from src.logger_config import setup_logging

logger = setup_logging(__name__)

class ArticleAnalysisMixin:
    """Mixin class providing shared article analysis functionality."""
    
    def __init__(self):
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0.0

    def analyze_results(self) -> Dict[str, any]:
        """
        Analyze article processing results and provide statistics.
        
        Returns:
            Dict containing analysis metrics including relevance percentages and ratios
        """
        total_articles = self.relevant + self.irrelevant
        if total_articles == 0:
            logger.warning("⚠️ No articles processed.")
            return {}

        relevant_percentage = (self.relevant / total_articles) * 100
        irrelevant_percentage = (self.irrelevant / total_articles) * 100
        ratio = self.relevant / self.irrelevant if self.irrelevant > 0 else float('inf')

        analysis_results = {
            "Relevant articles": self.relevant,
            "Irrelevant articles": self.irrelevant,
            "Total articles": total_articles,
            "Relevant percentage": f"{relevant_percentage:.2f}%",
            "Irrelevant percentage": f"{irrelevant_percentage:.2f}%",
            "Relevance ratio": f"{ratio:.2f}",
            "Max relevance score": self.max_relevance_score
        }

        # Log results
        for key, value in analysis_results.items():
            logger.info(f"{key}: {value}")
            print(f"{key}: {value}")

        # Analysis conclusion
        conclusion = (
            "✅ Most articles are relevant, indicating well-targeted search."
            if relevant_percentage > 50
            else "⚠️ Most articles are irrelevant, suggesting search criteria refinement needed."
        )
        logger.info(conclusion)
        print(conclusion)
        
        return analysis_results