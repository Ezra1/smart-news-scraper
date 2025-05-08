import os
import json
import logging
import re
from dotenv import load_dotenv
from pathlib import Path
from src.database_manager import DatabaseManager, ArticleManager
from src.config import ConfigManager
from typing import Optional, Dict

from src.logger_config import setup_logging
logger = setup_logging(__name__)

# Load environment variables and set up logging
load_dotenv()
OUTPUT_DIR = Path("output")

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
                    # Insert the article data into the relevant_articles table
                    self.article_manager.insert_relevant_article(
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
        """
        Process the most recent results file.
        
        This method attempts to read from JSONL files in the output directory.
        If no files are found, it falls back to processing articles directly from the database.
        """
        try:
            # First try to process from files
            output_files = sorted(OUTPUT_DIR.glob("results_*.jsonl"), key=os.path.getmtime, reverse=True)
            if output_files:
                latest_results_file = output_files[0]
                logger.info(f"📂 Processing results from {latest_results_file}")

                with open(latest_results_file, "r", encoding="utf-8") as results_file:
                    for line in results_file:
                        try:
                            result = json.loads(line)
                            self.process_result(result)
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Invalid JSON in results file: {e}")
                
                logger.info("✅ Results processing from file complete.")
            else:
                logger.info("No results files found. Processing directly from database...")
                self.process_from_database()
        except Exception as error:
            logger.error(f"❌ Error processing results: {error}")
            
    def process_from_database(self):
        """
        Process articles directly from the database.
        
        This method retrieves articles from the relevant_articles table
        and processes them for relevance analysis.
        """
        try:
            # Get all articles from the relevant_articles table
            query = """
                SELECT c.*, r.id as raw_article_id 
                FROM relevant_articles c
                JOIN raw_articles r ON c.raw_article_id = r.id
            """
            results = self.article_manager.db_manager.execute_query(query)
            
            if not results:
                logger.info("No relevant articles found in the database.")
                return
                
            logger.info(f"Processing {len(results)} articles from database...")
            
            # Process each article
            for article in results:
                # Create a result object similar to what would be in the JSONL file
                result = {
                    "raw_article_id": article["raw_article_id"],
                    "url": article["url"],
                    "relevance_score": article["relevance_score"]
                }
                self.process_result(result)
                
            logger.info("✅ Database processing complete.")
        except Exception as error:
            logger.error(f"❌ Error processing from database: {error}")

if __name__ == "__main__":
    db_manager = DatabaseManager()
    try:
        article_manager = ArticleManager(db_manager)
        relevance_filter = RelevanceFilter(article_manager)
        relevance_filter.process_latest_results()
        
        # If no files found, process directly from database
        if relevance_filter.relevant + relevance_filter.irrelevant == 0:
            logger.info("No results files found. Processing directly from database...")
            # Future implementation for direct database processing
        
        # Analyze the results
        relevance_filter.analyze_results()
    finally:
        db_manager.close()