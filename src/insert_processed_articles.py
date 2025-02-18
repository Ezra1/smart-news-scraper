import os
import json
import logging
import re
from dotenv import load_dotenv
from pathlib import Path
from src.database_manager import DatabaseManager, ArticleManager
from src.config import ConfigManager
from typing import Optional, Dict

# Load environment variables and set up logging
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")

class RelevanceFilter:
    """Handles extraction and processing of results to determine article relevance."""

    def __init__(self, article_manager: ArticleManager):
        """Initialize with shared ArticleManager instance"""
        config_manager = ConfigManager()
        self.article_manager = article_manager
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0
        self.RELEVANCE_THRESHOLD = float(config_manager.get("RELEVANCE_THRESHOLD"))

    def extract_json_content(self, content: str) -> Optional[Dict]:
        """Extract and parse JSON content from the OpenAI response."""
        try:
            # Try direct JSON parsing
            return json.loads(content)
        except json.JSONDecodeError:
            # If direct parsing fails, attempt to extract JSON from Markdown format
            match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    logger.error(f"❌ Failed to parse extracted JSON from response: {content[:100]}...")
                    return None
            else:
                logger.error(f"❌ JSON content not found in expected format: {content[:100]}...")
                return None

    def process_result(self, result: Dict):
        """Process a single result and insert relevant articles into cleaned_articles."""
        try:
            # Load the raw_article_id
            raw_article_id = result.get("raw_article_id")
            if not raw_article_id:
                logger.error("❌ Missing raw_article_id in result.")
                return
            
            # Load the url
            url = result.get("url")
            if not url:
                logger.error(f"❌ Missing URL in result for article ID: {raw_article_id}")
                return
            
            # Load the relevance score
            relevance_score = result.get("relevance_score")
            if relevance_score is None:
                logger.error(f"❌ Missing relevance_score in result for article ID: {raw_article_id}")
                return

            if relevance_score >= self.RELEVANCE_THRESHOLD:
                # Retrieve the article data from the raw_articles table
                article_data = self.article_manager.get_article_by_id(raw_article_id)

                if article_data:
                    self.relevant += 1
                    self.max_relevance_score = max(self.max_relevance_score, relevance_score)
                    # Insert the article data into the cleaned_articles table
                    self.article_manager.insert_cleaned_article(
                        raw_article_id=article_data["id"],
                        title=article_data["title"],
                        content=article_data["content"],
                        source=article_data["source"],
                        url=article_data["url"],
                        url_to_image=article_data.get("url_to_image"),
                        published_at=article_data["published_at"],
                        relevance_score=relevance_score
                    )
                    logger.info(f"✅ Inserted relevant article '{article_data['title']}' with score {relevance_score}")
                else:
                    logger.warning(f"⚠️ Article data not found for article ID: {raw_article_id}")
            else:
                self.irrelevant += 1
                logger.info(f"❌ Article with ID '{raw_article_id}' is not relevant (score: {relevance_score})")

        except Exception as error:
            logger.error(f"❌ Error processing result for article ID {raw_article_id}: {error}")

    def process_latest_results(self):
        """Process the most recent results file."""
        try:
            output_files = sorted(OUTPUT_DIR.glob("results_*.jsonl"), key=os.path.getmtime, reverse=True)
            if not output_files:
                logger.error("❌ No output files found in the output directory.")
                return

            latest_results_file = output_files[0]
            logger.info(f"📂 Processing results from {latest_results_file}")

            with open(latest_results_file, "r", encoding="utf-8") as results_file:
                for line in results_file:
                    try:
                        result = json.loads(line)
                        self.process_result(result)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Invalid JSON in results file: {e}")

            logger.info("✅ Results processing complete.")
        except Exception as error:
            logger.error(f"❌ Error processing results: {error}")

    def analyze_results(self):
        """Analyze the results after processing output."""
        total_articles = self.relevant + self.irrelevant
        if total_articles == 0:
            logger.warning("⚠️ No articles processed.")
            return

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

        # Log and print results
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

if __name__ == "__main__":
    db_manager = DatabaseManager()
    try:
        article_manager = ArticleManager(db_manager)
        relevance_filter = RelevanceFilter(article_manager)
        relevance_filter.process_latest_results()
        relevance_filter.analyze_results()
    finally:
        db_manager.close()