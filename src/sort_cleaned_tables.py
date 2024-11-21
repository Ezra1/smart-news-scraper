"""src/sort_cleaned_tables.py"""

import os
import json
import logging
import logging.config
import re
from dotenv import load_dotenv
from pathlib import Path
from src.database import DatabaseManager, ArticleManager

# Load environment variables and set up logging
load_dotenv()
current_directory = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')

# Set up logging
logging.config.fileConfig(logging_config_path)
logger = logging.getLogger(__name__)

# Constants
OUTPUT_DIR = Path("openAIFiles/output")

class RelevanceFilter:
    """Handles the extraction and processing of batch results to determine article relevance."""

    def __init__(self, article_manager):
        self.article_manager = article_manager
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0
        # Default to 0.7 if not set in environment
        self.RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.7"))

    def extract_json_content(self, content):
        """Extract and parse JSON content from the model's response."""
        try:
            # First try direct JSON parsing
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If direct parsing fails, try extracting from markdown code blocks
                match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
                else:
                    raise ValueError("JSON content not found in expected format.")
        except Exception as e:
            logging.error(f"JSON parse error in content '{content[:100]}...': {e}")
            return None

    def process_result(self, result):
        """Process a single batch result and insert relevant articles into cleaned_articles."""
        try:
            custom_id = result.get("custom_id")
            if not custom_id:
                logging.error("Missing custom_id in result")
                return

            response = result.get("response", {})
            choices = response.get("body", {}).get("choices", [])
            if not choices:
                logging.error(f"No choices found in response for {custom_id}")
                return

            response_content = choices[0].get("message", {}).get("content", "")
            relevance_data = self.extract_json_content(response_content)

            if relevance_data:
                title = relevance_data.get("title")
                relevance_score = float(relevance_data.get("relevance_score", 0))

                if relevance_score >= self.RELEVANCE_THRESHOLD:
                    try:
                        article_id = int(custom_id.split("-")[1])
                    except (IndexError, ValueError) as e:
                        logging.error(f"Invalid custom_id format: {custom_id}: {e}")
                        return

                    article_data = self.article_manager.get_articles(article_id)

                    if article_data:
                        self.relevant += 1
                        self.max_relevance_score = max(self.max_relevance_score, relevance_score)
                        self.article_manager.insert_cleaned_article(
                            raw_article_id=article_data["id"],
                            title=title,
                            content=article_data["content"],
                            source=article_data["source"],
                            url=article_data["url"],
                            url_to_image=article_data.get("url_to_image"),  # Use get() with default None
                            published_at=article_data["published_at"],
                            relevance_score=relevance_score
                        )
                        logging.info(f"Inserted relevant article '{title}' with score {relevance_score}")
                    else:
                        logging.warning(f"Article data not found for article ID: {article_id}")
                else:
                    self.irrelevant += 1
                    logging.info(f"Article '{title}' is not relevant (score: {relevance_score})")
            else:
                logging.error(f"Failed to extract relevance data from response for {custom_id}")

        except Exception as error:
            logging.error(f"Error processing result for {custom_id}: {error}")

    def process_latest_results(self):
        """Process the most recent batch results file."""
        try:
            output_files = sorted(OUTPUT_DIR.glob("batch_output_*.jsonl"), key=os.path.getmtime, reverse=True)
            if not output_files:
                logging.error("No batch output files found in the output directory")
                return

            latest_results_file = output_files[0]
            logging.info(f"Processing results from {latest_results_file}")
            
            with open(latest_results_file, "r", encoding="utf-8") as results_file:
                for line in results_file:
                    try:
                        result = json.loads(line)
                        self.process_result(result)
                    except json.JSONDecodeError as e:
                        logging.error(f"Invalid JSON in results file: {e}")
                        continue

            logging.info("Batch results processing complete")
        except Exception as error:
            logging.error(f"Error processing batch results: {error}")
            raise

    def analyze_results(self):
        """Analyze the results after processing batch output."""
        total_articles = self.relevant + self.irrelevant
        if total_articles == 0:
            logging.warning("No articles processed")
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
            message = f"{key}: {value}"
            logging.info(message)
            print(message)

        # Analysis conclusion
        conclusion = ("Most articles are relevant, indicating well-targeted search." 
                     if relevant_percentage > 50 
                     else "Most articles are irrelevant, suggesting search criteria refinement needed.")
        logging.info(conclusion)
        print(conclusion)