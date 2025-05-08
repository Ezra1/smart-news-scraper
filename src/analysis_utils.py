"""Utility functions for analyzing article relevance results."""

import logging
from typing import Dict, Any

from src.logger_config import setup_logging
logger = setup_logging(__name__)

def analyze_relevance_results(relevant: int, irrelevant: int, max_relevance_score: float) -> Dict[str, Any]:
    """
    Analyze article relevance results and generate statistics.
    
    Args:
        relevant: Number of relevant articles
        irrelevant: Number of irrelevant articles
        max_relevance_score: Maximum relevance score found
        
    Returns:
        Dict containing analysis results and statistics
    """
    total_articles = relevant + irrelevant
    if total_articles == 0:
        logger.warning("⚠️ No articles processed.")
        return {
            "Relevant articles": 0,
            "Irrelevant articles": 0,
            "Total articles": 0,
            "Relevant percentage": "0.00%",
            "Irrelevant percentage": "0.00%",
            "Relevance ratio": "0.00",
            "Max relevance score": 0.0,
            "Conclusion": "⚠️ No articles processed."
        }

    relevant_percentage = (relevant / total_articles) * 100
    irrelevant_percentage = (irrelevant / total_articles) * 100
    ratio = relevant / irrelevant if irrelevant > 0 else float('inf')

    # Determine conclusion based on relevance percentage
    conclusion = (
        "✅ Most articles are relevant, indicating well-targeted search."
        if relevant_percentage > 50
        else "⚠️ Most articles are irrelevant, suggesting search criteria refinement needed."
    )

    return {
        "Relevant articles": relevant,
        "Irrelevant articles": irrelevant,
        "Total articles": total_articles,
        "Relevant percentage": f"{relevant_percentage:.2f}%",
        "Irrelevant percentage": f"{irrelevant_percentage:.2f}%",
        "Relevance ratio": f"{ratio:.2f}",
        "Max relevance score": max_relevance_score,
        "Conclusion": conclusion
    }

def print_analysis_results(analysis_results: Dict[str, Any]) -> None:
    """
    Print analysis results in a formatted way.
    
    Args:
        analysis_results: Dictionary containing analysis results
    """
    # Log and print results
    for key, value in analysis_results.items():
        if key != "Conclusion":  # Skip conclusion for now
            logger.info(f"{key}: {value}")
            print(f"{key}: {value}")
    
    # Print conclusion separately
    logger.info(analysis_results["Conclusion"])
    print(analysis_results["Conclusion"])