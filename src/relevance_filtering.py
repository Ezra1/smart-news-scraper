import os
import time
import logging
import logging.config
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
from openai import OpenAI
from src.database import get_articles

# Load environment variables and set up logging
# Get the absolute path to the logging.conf file
current_directory = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')

# Set up logging
logging.config.fileConfig(logging_config_path)
logger = logging.getLogger(__name__)
load_dotenv()

class BatchProcessor:
    """Handles the creation, uploading, and processing of batch jobs for article relevance scoring."""

    RELEVANCE_THRESHOLD = 0.7
    BATCH_INPUT_PATH = Path("openAIFiles/input/batch_input.jsonl")
    
    def __init__(self):
        # Initialize OpenAI client with the API key from the environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logging.error("OPENAI_API_KEY is missing in environment.")
            raise ValueError("OPENAI_API_KEY is not set.")
        
        self.client = OpenAI(api_key=api_key)
    
    class RelevanceResponse(BaseModel):
        """Schema for the relevance response"""
        title: str
        relevance_score: float

    def create_jsonl_for_batch(self, articles):
        """Generate a JSONL file for batch relevance scoring."""
        self.BATCH_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)  # Ensure input directory exists
        logging.info("Storing batch input json in: %s", self.BATCH_INPUT_PATH)

        with open(self.BATCH_INPUT_PATH, "w", encoding="utf-8") as jsonl_file:
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

    def upload_jsonl_file(self):
        """Upload the JSONL file and return the file ID."""
        try:
            with open(self.BATCH_INPUT_PATH, "rb") as file:
                response = self.client.files.create(file=file, purpose="batch")
                logging.info("Batch file uploaded successfully. File ID: %s", response.id)
                return response.id
        except Exception as error:
            logging.error("Error uploading JSONL file: %s", error)
        return None

    def create_batch_job(self, file_id):
        """Create a batch job using the uploaded JSONL file ID and return the batch ID."""
        try:
            batch = self.client.batches.create(
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

    def check_batch_status(self, batch_id):
        """Check the status of a batch job periodically and retrieve results if completed."""
        try:
            while True:
                batch_status = self.client.batches.retrieve(batch_id)
                if batch_status.status == "completed":
                    output_file_id = batch_status.output_file_id
                    output_file_path = (
                        f"openAIFiles/output/batch_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
                    )
                    output_file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure output directory exists
                    
                    with open(output_file_path, "w", encoding="utf-8") as output_file:
                        file_response = self.client.files.content(output_file_id)
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

    def process_batch(self):
        """Handles the entire batch process from JSONL creation to batch processing."""
        articles = get_articles()  # Get articles to process
        if not articles:
            logging.error("No articles found for processing.")
            return
        
        self.create_jsonl_for_batch(articles)
        
        file_id = self.upload_jsonl_file()
        if not file_id:
            logging.error("Batch file upload failed.")
            return
        
        batch_id = self.create_batch_job(file_id)
        if not batch_id:
            logging.error("Batch job creation failed.")
            return
        
        results_path = self.check_batch_status(batch_id)
        if results_path:
            logging.info("Batch processing completed and output file saved.")
        else:
            logging.error("Batch processing failed or no results available.")


if __name__ == "__main__":
    # Create instance of BatchProcessor and start the batch process
    batch_processor = BatchProcessor()
    batch_processor.process_batch()
