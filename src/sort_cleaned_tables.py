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
logging.config.fileConfig('logging.conf')
logger = logging.getLogger(__name__)

# Constants
OUTPUT_DIR = Path("openAIFiles/output")


class RelevanceFilter:
    """Handles the extraction and processing of batch results to determine article relevance."""

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.article_manager = ArticleManager(db_manager)
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0
        self.RELEVANCE_THRESHOLD = os.getenv("RELEVANCE_THRESHOLD")

    def extract_json_content(self, content):
        """Extract and parse JSON content from the model's response."""
        try:
            # Using regex to match JSON within triple backticks
            match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            else:
                raise ValueError("JSON content not found in expected format.")
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error: {e}")
        return None

    def process_result(self, result):
        """Process a single batch result and insert relevant articles into cleaned_articles."""
        try:
            custom_id = result["custom_id"]
            response_body = result.get("response", {}).get("body", {}).get("choices", [])[0].get("message", {}).get("content", "")
            relevance_data = self.extract_json_content(response_body)

            if relevance_data:
                title = relevance_data.get("title")
                relevance_score = relevance_data.get("relevance_score", 0)

                if relevance_score >= RELEVANCE_THRESHOLD:
                    article_id = int(custom_id.split("-")[1])
                    article_data = self.article_manager.get_articles(article_id)

                    if article_data:
                        # Insert the article into the cleaned_articles table if it meets the relevance threshold
                        self.relevant += 1
                        self.max_relevance_score = max(self.max_relevance_score, relevance_score)
                        self.article_manager.insert_cleaned_article(
                            raw_article_id=article_data["id"],
                            title=title,
                            content=article_data["content"],
                            source=article_data["source"],
                            url=article_data["url"],
                            url_to_image=article_data["url_to_image"],
                            published_at=article_data["published_at"],
                            relevance_score=relevance_score
                        )
                        logging.info(f"Inserted relevant article '{title}' with score {relevance_score}.")
                    else:
                        logging.warning(f"Article data not found for article ID: {article_id}")
                else:
                    self.irrelevant += 1
                    logging.info(f"Article '{title}' is not relevant (score: {relevance_score}). Skipping.")

        except Exception as error:
            logging.error(f"Error processing result for {custom_id}: {error}")

    def process_batch_results(self, results_path):
        """Process all batch results from a JSONL output file."""
        if results_path and results_path.exists():
            with open(results_path, "r", encoding="utf-8") as results_file:
                for line in results_file:
                    result = json.loads(line)
                    self.process_result(result)
            logging.info("Batch results processing complete.")
        else:
            logging.error("No results file found or available for processing.")

    def analyse_results(self):
        """Analyze the results after processing batch output."""
        total_articles = self.relevant + self.irrelevant
        relevant_percentage = (self.relevant / total_articles) * 100 if total_articles > 0 else 0
        irrelevant_percentage = (self.irrelevant / total_articles) * 100 if total_articles > 0 else 0
        ratio = self.relevant / self.irrelevant if self.irrelevant > 0 else float('inf')  # Handle division by zero if no irrelevant articles

        print(f"Number of relevant articles: {self.relevant}")
        print(f"Number of irrelevant articles: {self.irrelevant}")
        print(f"Total articles analyzed: {total_articles}")
        print(f"Percentage of relevant articles: {relevant_percentage:.2f}%")
        print(f"Percentage of irrelevant articles: {irrelevant_percentage:.2f}%")
        print(f"Ratio of relevant to irrelevant articles: {ratio:.2f}")
        print(f"Max relevance score: {self.max_relevance_score}")

        # Analysis of relevance
        if relevant_percentage > 50:
            print("Most articles are relevant, indicating a well-targeted search.")
        else:
            print("Most articles are irrelevant, suggesting the search criteria may need refinement.")

    def run(self):
        """Main function to locate and process the latest batch results file."""
        # Find the most recent output file in the OUTPUT_DIR
        output_files = sorted(OUTPUT_DIR.glob("batch_output_*.jsonl"), key=os.path.getmtime, reverse=True)
        if output_files:
            latest_results_file = output_files[0]
            logging.info(f"Processing results from {latest_results_file}")
            self.process_batch_results(latest_results_file)
        else:
            logging.error("No batch output files found in the output directory.")

        self.analyse_results()