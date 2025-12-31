from dataclasses import asdict
from typing import Any, Dict

from src.analysis_utils import calculate_relevance_stats, print_analysis_results
from src.logger_config import setup_logging

logger = setup_logging(__name__)

class ArticleAnalysisMixin:
    """Mixin class providing shared article analysis functionality."""
    
    def __init__(self):
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0.0

    def analyze_results(self) -> Dict[str, Any]:
        """Analyze article processing results and provide statistics."""
        stats = calculate_relevance_stats(
            relevant=self.relevant,
            irrelevant=self.irrelevant,
            max_score=self.max_relevance_score,
        )
        # Side-effect logging/printing retained via utility for parity
        print_analysis_results(stats)
        return asdict(stats)