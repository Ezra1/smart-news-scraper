import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
from openai import OpenAI
from src.database import get_articles

# Set up logging
log_file_path = Path("openAIFiles/logs/batch_processing.log")
log_file_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, filename=log_file_path)

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("OPENAI_API_KEY is missing in environment.")
    raise ValueError("OPENAI_API_KEY is not set.")

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
                "Please evaluate the relevance of the article below to the topics 'pharmaceutical security', "
                "'regulatory compliance', 'international law enforcement coordination', 'data analysis for tracking "
                "counterfeit products', and 'the development of anti-counterfeiting strategies'.\n\n"
                "Return a JSON object containing:\n"
                "- 'id': The ID for the article\n"
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
    except Exception as error:
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

def main():
    """Main function to handle batch processing."""
    articles = get_articles()
    create_jsonl_for_batch(articles)
    
    file_id = upload_jsonl_file()
    if not file_id:
        logging.error("Batch file upload failed.")
        return
    
    batch_id = create_batch_job(file_id)
    if not batch_id:
        logging.error("Batch job creation failed.")
        return
    
    results_path = check_batch_status(batch_id)
    if results_path:
        logging.info("Batch processing completed and output file saved.")
    else:
        logging.error("Batch processing failed or no results available.")

if __name__ == "__main__":
    main()
