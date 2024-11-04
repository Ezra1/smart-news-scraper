import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
import re
from dotenv import load_dotenv
from pydantic import BaseModel
from openai import OpenAI
from src.database import get_articles, insert_cleaned_article

# Set up logging
logging.basicConfig(level=logging.INFO, filename='openAIFiles/logs/batch_processing.log')

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Constants
RELEVANCE_THRESHOLD = 0.7
BATCH_INPUT_PATH = Path("openAIFiles/input/batch_input.jsonl")

class RelevanceResponse(BaseModel):
    """Schema for the relevance response"""
    title: str
    relevance_score: float

def create_jsonl_for_batch(articles):
    """Generate a JSONL file for batch relevance scoring."""
    with open(BATCH_INPUT_PATH, "w", encoding="utf-8") as jsonl_file:
        for article in articles:
            article_id, title, content = article["id"], article["title"], article["content"]
            prompt = (
                "Please evaluate the relevance of the article below to the topic 'pharmaceutical security'.\n\n"
                "Return a JSON object containing:\n"
                "- 'title': The title of the article\n"
                "- 'relevance_score': A relevance score from 0 (completely irrelevant) to 1 (highly relevant)\n\n"
                f"Article Title: '{title}'\n\nArticle Content: {content}\n\n"
            )

            json_line = {
                "custom_id": f"article-{article_id}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "Return the relevance score and title as a JSON object."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 50,
                    "temperature": 0.0
                }
            }
            jsonl_file.write(json.dumps(json_line) + "\n")
    logging.info("JSONL file created successfully.")

def upload_jsonl_file():
    """Upload the JSONL file and return the file ID."""
    try:
        with open(BATCH_INPUT_PATH, "rb") as file:
            response = client.files.create(file=file, purpose="batch")
            return response.id
    except Exception as error:  # Broad exception narrowed to catch specific issues later
        logging.error("Error uploading JSONL file: %s", error)
    return None

def create_batch_job(file_id):
    """Create a batch job using the uploaded JSONL file ID and return the batch ID."""
    try:
        batch = client.batches.create(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={"description": "Batch relevance scoring for articles"}
        )
        logging.info("Batch job created with ID: %s", batch.id)
        return batch.id
    except Exception as error:
        logging.error("Error creating batch job: %s", error)
    return None

def check_batch_status(batch_id):
    """Check the status of a batch job periodically and retrieve results if completed."""
    try:
        while True:
            batch_status = client.batches.retrieve(batch_id)
            if batch_status.status == "completed":
                output_file_id = batch_status.output_file_id
                output_file_path = (
                    f"openAIFiles/output/batch_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
                )
                with open(output_file_path, "w", encoding="utf-8") as output_file:
                    file_response = client.files.content(output_file_id)
                    output_file.write(file_response.text)
                    logging.info("Output file %s created successfully.", output_file_path)
                return output_file_path
            if batch_status.status in ["failed", "expired"]:
                logging.error("Batch job %s failed or expired.", batch_id)
                break
            logging.info("Batch job %s in progress... Checking again in 5 minutes.", batch_id)
            time.sleep(300)
    except Exception as error:
        logging.error("Error checking batch status: %s", error)
    return None

def extract_json_content(content):
    """Extract and parse JSON content from the model's response."""
    try:
        match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError("JSON content not found in expected format.")
    except json.JSONDecodeError as error:
        logging.error("JSON decode error: %s", error)
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
                article_data = get_articles(article_id=article_id)

                if article_data:
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
                    logging.info("Inserted relevant article '%s' with score %s.", title, relevance_score)
                else:
                    logging.warning("Article data not found for article ID: %s", article_id)
            else:
                logging.info("Article '%s' is not relevant (score: %s). Skipping.", title, relevance_score)

    except Exception as error:
        logging.error("Error processing result for %s: %s", custom_id, error)

def main():
    """Main function to handle batch processing."""
    articles = get_articles()
    create_jsonl_for_batch(articles)
    batch_id = upload_batch()

    if batch_id:
        results_path = check_batch_status(batch_id)
        if results_path:
            with open(results_path, "r", encoding="utf-8") as results_file:
                for line in results_file:
                    result = json.loads(line)
                    process_result(result)
        else:
            logging.warning("No results to process.")
    else:
        logging.error("Batch creation failed.")

if __name__ == "__main__":
    main()
