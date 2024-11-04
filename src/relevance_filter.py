import os
import json
import openai
import time
import logging
import datetime
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
from src.database import get_articles, insert_cleaned_article
from openai import OpenAI

# Set up logging
logging.basicConfig(level=logging.INFO, filename='batch_processing.log')

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Constants
RELEVANCE_THRESHOLD = 0.7
BATCH_INPUT_PATH = Path("config/batch_input.jsonl")

# Define structured response schema using Pydantic
class RelevanceResponse(BaseModel):
    title: str
    relevance_score: float

def create_jsonl_for_batch(articles):
    """Generate a JSONL file for batch relevance scoring."""
    with open(BATCH_INPUT_PATH, "w") as jsonl_file:
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
                "url": "/v1/chat/completions",  # Updated endpoint
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
    print("JSONL file created successfully.")

def upload_jsonl_file():
    """Upload the JSONL file and return the file ID."""
    try:
        with open(BATCH_INPUT_PATH, "rb") as file:
            response = client.files.create(file=file, purpose="batch")
            return response.id
    except openai.error.InvalidRequestError as e:
        print(f"Invalid request error while uploading JSONL file: {e}")
        return None
    except Exception as e:
        print(f"Error uploading JSONL file: {e}")
        return None

def create_batch_job(file_id):
    """Create a batch job using the uploaded JSONL file ID and return the batch ID."""
    try:
        batch = client.batches.create(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",  # Updated endpoint
            completion_window="24h",
            metadata={"description": "Batch relevance scoring for articles"}
        )
        print(f"Batch job created with ID: {batch.id}")
        return batch.id
    except openai.error.InvalidRequestError as e:
        print(f"Invalid request error while creating batch job: {e}")
        return None
    except Exception as e:
        print(f"Error creating batch job: {e}")
        return None

def check_batch_status(batch_id):
    """Check the status of a batch job periodically and retrieve results if completed."""
    try:
        while True:
            batch_status = client.batches.retrieve(batch_id)
            if batch_status.status == "completed":
                output_file_id = batch_status.output_file_id
                file_response = client.files.content(f"{output_file_id}")
                with open(f"openAIFiles/batch_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl") as output_file:
                    output_file.write(output_file.text)
                    print(f"Output file {output_file} created")
                # return client.files.download(output_file_id).text
            elif batch_status.status in ["failed", "expired"]:
                print(f"Batch job {batch_id} failed or expired.")
                break
            else:
                print(f"Batch job {batch_id} is still in progress... Checking again in 5 minutes.")
                time.sleep(300)  # Polling delay before checking again
    except Exception as e:
        print(f"Error checking batch status: {e}")
    return None

def process_result(result):
    """Process a single batch result and insert relevant articles into cleaned_articles."""
    try:
        custom_id = result["custom_id"]
        response_body = result.get("response", {}).get("body", {}).get("choices", [])[0].get("message", {}).get("content", {})
        relevance_data = json.loads(response_body)  # Parse the response if it's returned as JSON text

        title = relevance_data.get("title")
        relevance_score = relevance_data.get("relevance_score", 0)

        # Check if the relevance score meets the threshold
        if relevance_score >= RELEVANCE_THRESHOLD:
            article_id = int(custom_id.split("-")[1])

            # Retrieve full article data by ID
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
                print(f"Inserted relevant article '{title}' with score {relevance_score}.")
            else:
                print(f"Article data not found for article ID: {article_id}")
        else:
            print(f"Article '{title}' is not relevant (score: {relevance_score}). Skipping.")

    except json.JSONDecodeError as e:
        print(f"JSON decode error while processing result for {result['custom_id']}: {e}")
    except Exception as e:
        print(f"Error processing result for {result['custom_id']}: {e}")

def upload_batch():
    """Upload the JSONL file, create a batch job, and process results."""
    file_id = upload_jsonl_file()
    if not file_id:
        print("Failed to upload JSONL file.")
        return

    batch_id = create_batch_job(file_id)
    logging.info(f"Batch job started with file: {BATCH_INPUT_PATH}")
    if not batch_id:
        print("Failed to create batch job.")
        return
    return batch_id

def main():
    # Step 1: Retrieve raw articles
    articles = get_articles()  # assuming get_articles() fetches all articles if no ID is provided

    # Step 2: Create JSONL file for batch processing
    create_jsonl_for_batch(articles)
   
    # Step 3: Upload and process batch
    batch_id = upload_batch()  # Capture batch_id here

    if batch_id is None:
        print("Batch creation failed.")
        return

    # Step 4: Check batch status and process results
    results = check_batch_status(batch_id)

    if results:
        for line in results.strip().splitlines():
            result = json.loads(line)
            process_result(result)
    else:
        print("No results to process yet.")

    batch_status = client.batches.retrieve(f"{batch_id}")
    print(batch_status.errors)

    

if __name__ == "__main__":
    main()
