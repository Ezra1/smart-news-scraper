import json
import logging
import re
from typing import Optional, Dict

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # graceful fallback if dependency not installed
    def load_dotenv(*args, **kwargs):
        return None

from src.database_manager import DatabaseManager, ArticleManager
from src.config import ConfigManager

from src.logger_config import setup_logging
logger = setup_logging(__name__)

# Load environment variables and set up logging
load_dotenv()

from src.analysis_base import ArticleAnalysisMixin

class RelevanceFilter(ArticleAnalysisMixin):
    """Handles extraction and processing of results to determine article relevance."""

    def __init__(self, article_manager: ArticleManager):
        super().__init__()  # Initialize analysis mixin
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
        raw_article_id = None
        try:
            # Load the raw_article_id
            raw_article_id = result.get("raw_article_id")
            if not raw_article_id:
                logger.error("❌ Missing raw_article_id in result.")
                return
            
            # Load the relevance score
            relevance_score = result.get("relevance_score")
            if relevance_score is None:
                logger.error(f"❌ Missing relevance_score in result for article ID: {raw_article_id}")
                return
            status = result.get("status") or result.get("processing_status")
            if status not in {"relevant", "irrelevant"}:
                status = "relevant" if relevance_score >= self.RELEVANCE_THRESHOLD else "irrelevant"

            # Track the highest score seen across all articles
            self.max_relevance_score = max(self.max_relevance_score, relevance_score)

            if status == "relevant":
                article_data = result

                if article_data:
                    self.relevant += 1
                    # Insert the article data into the relevant_articles table
                    self.article_manager.insert_relevant_article(
                        raw_article_id=raw_article_id,
                        title=article_data.get("title", ""),
                        content=article_data.get("content", ""),
                        source=article_data.get("source", ""),
                        url=article_data.get("url", ""),
                        url_to_image=article_data.get("url_to_image"),
                        published_at=article_data.get("published_at", ""),
                        relevance_score=relevance_score
                    )
                    logger.info(f"✅ Inserted relevant article with ID {raw_article_id} (score {relevance_score})")
                else:
                    logger.warning(f"⚠️ Article data not found for article ID: {raw_article_id}")
            else:
                self.irrelevant += 1
                logger.info(f"❌ Article with ID '{raw_article_id}' is not relevant (score: {relevance_score})")

        except Exception as error:
            logger.error(f"❌ Error processing result for article ID {raw_article_id}: {error}")

    def process_latest_results(self):
        """
        Process the most recent results from the database as source of truth.
        """
        try:
            logger.info("Processing results from database...")
            self.process_from_database()
        except Exception as error:
            logger.error(f"❌ Error processing results: {error}")
            
    def process_from_database(self):
        """
        Process articles directly from the database using processing_results records.
        """
        try:
            # Reset counters before processing
            self.relevant = 0
            self.irrelevant = 0
            query = """
                SELECT 
                    pr.raw_article_id,
                    pr.relevance_score,
                    pr.status,
                    r.title,
                    r.content,
                    r.source,
                    r.url,
                    r.url_to_image,
                    r.published_at
                FROM processing_results pr
                JOIN raw_articles r ON pr.raw_article_id = r.id
            """
            results = self.article_manager.db_manager.execute_query(query)
            
            if not results:
                logger.info("No processed articles found in the database.")
                return
                
            logger.info(f"Processing {len(results)} articles from database...")
            
            # Process each article
            for article in results:
                # Create a result object similar to what would be in the JSONL file
                result = {
                    "raw_article_id": article["raw_article_id"],
                    "url": article["url"],
                    "relevance_score": article["relevance_score"],
                    "status": article.get("status"),
                    "title": article.get("title"),
                    "content": article.get("content"),
                    "source": article.get("source"),
                    "url_to_image": article.get("url_to_image"),
                    "published_at": article.get("published_at"),
                }
                self.process_result(result)
                
            logger.info("✅ Database processing complete.")
        except Exception as error:
            logger.error(f"❌ Error processing from database: {error}")

    def analyze_results(self) -> Dict[str, int]:
        """
        Analyze results using processing_results as canonical source.
        Ensures analytics reflect both relevant and irrelevant outcomes.
        """
        stats = self.article_manager.get_processing_stats()
        self.relevant = stats["relevant"]
        self.irrelevant = stats["irrelevant"]
        self.max_relevance_score = stats.get("max_score", 0.0)
        return super().analyze_results()

    def get_relevance_stats(self) -> Dict[str, int]:
        """Return relevance counts aggregated from processing_results."""
        return self.article_manager.get_relevance_stats()

if __name__ == "__main__":
    db_manager = DatabaseManager()
    try:
        article_manager = ArticleManager(db_manager)
        relevance_filter = RelevanceFilter(article_manager)
        relevance_filter.process_latest_results()

        # Analyze the results
        relevance_filter.analyze_results()
    finally:
        db_manager.close()