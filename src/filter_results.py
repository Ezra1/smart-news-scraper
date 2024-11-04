import os
import json
import logging
import re
from dotenv import load_dotenv
from pathlib import Path
from src.database import get_article_data_by_id, insert_cleaned_article

# Load environment variables and set up logging
load_dotenv()
logging.basicConfig(level=logging.INFO, filename="openAIFiles/logs/filter_processing.log")

# Constants
RELEVANCE_THRESHOLD = 0.7
RELEVANT = 0
IRRELEVANT = 0
OUTPUT_DIR = Path("openAIFiles/output")

def extract_json_content(content):
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

def process_result(result):
    """Process a single batch result and insert relevant articles into cleaned_articles."""
    try:
        custom_id = result["custom_id"]
        response_body = result.get("response", {}).get("body", {}).get("choices", [])[0].get("message", {}).get("content", "")
        relevance_data = extract_json_content(response_body)

        if relevance_data:
            title = relevance_data.get("title")
            relevance_score = relevance_data.get("relevance_score", 0)

            if relevance_score >= RELEVANCE_THRESHOLD:
                article_id = int(custom_id.split("-")[1])
                article_data = get_article_data_by_id(article_id)

                if article_data:
                    # Insert the article into the cleaned_articles table if it meets the relevance threshold
                    insert_cleaned_article(
                        raw_article_id=article_data["id"],
                        title=title,
                        content=article_data["content"],
                        source=article_data["source"],
                        url=article_data["url"],
                        urlToImage=article_data["urltoimage"],
                        published_at=article_data["published_at"],
                        relevance_score=relevance_score
                    )
                    logging.info(f"Inserted relevant article '{title}' with score {relevance_score}.")
                else:
                    logging.warning(f"Article data not found for article ID: {article_id}")
            else:
                logging.info(f"Article '{title}' is not relevant (score: {relevance_score}). Skipping.")

    except Exception as error:
        logging.error(f"Error processing result for {custom_id}: {error}")

def process_batch_results(results_path):
    """Process all batch results from a JSONL output file."""
    if results_path and results_path.exists():
        with open(results_path, "r", encoding="utf-8") as results_file:
            for line in results_file:
                result = json.loads(line)
                process_result(result)
        logging.info("Batch results processing complete.")
    else:
        logging.error("No results file found or available for processing.")

def main():
    """Main function to locate and process the latest batch results file."""
    # Find the most recent output file in the OUTPUT_DIR
    output_files = sorted(OUTPUT_DIR.glob("batch_output_*.jsonl"), key=os.path.getmtime, reverse=True)
    print(f"output_files: {output_files}")
    directory = Path(OUTPUT_DIR)
    for item in directory.iterdir():
        print(item)
    if output_files:
        latest_results_file = output_files[0]
        logging.info(f"Processing results from {latest_results_file}")
        process_batch_results(latest_results_file)
    else:
        logging.error("No batch output files found in the output directory.")

if __name__ == "__main__":
    main()
