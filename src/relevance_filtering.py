import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from openai import OpenAI
from openai import OpenAIError, AuthenticationError, RateLimitError, APIConnectionError, APITimeoutError
from pydantic import BaseModel

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from database import ArticleManager, DatabaseManager  # Import database access methods
from config import ConfigManager

class BatchRequest(BaseModel):
    custom_id: str
    method: str = "POST"
    url: str = "/v1/chat/completions"
    body: Dict[str, Any]

class BatchProcessor:
    """Handles batch processing using OpenAI's Batch API"""

    def __init__(self):
        config_manager = ConfigManager()
        self.OPENAI_API_KEY = config_manager.get("OPENAI_API_KEY")

        if not self.OPENAI_API_KEY:
            logging.error("❌ Missing OpenAI API Key. Ensure it is set in config.json.")
            raise ValueError("Missing OpenAI API Key.")

        OpenAI.api_key = self.OPENAI_API_KEY
        self.client = OpenAI()
        self.input_dir = Path("batch/input")
        self.output_dir = Path("batch/output")
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


    def send_openai_request(self, article: Dict[str, Any], model: str = "gpt-4o-mini") -> Optional[Dict]:
        """Send an article for processing and handle API errors."""
        prompt = (
            "Evaluate the article's relevance to pharmaceutical security, regulatory compliance, "
            "and anti-counterfeiting strategies.\n\n"
            f"Title: {article.get('title', '')}\n"
            f"Content: {article.get('content', '')}"
        )

        attempt = 0
        max_attempts = 5
        wait_time = 5  # Start with 5 seconds wait for rate limits

        while attempt < max_attempts:
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Evaluate article relevance and return a score from 0-1."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=150,
                    temperature=0
                )

                # Validate response format before returning
                if not response or "choices" not in response:
                    logger.error(f"❌ Unexpected OpenAI response format: {response}")
                    return None

                return response.choices[0].message.content  # Extract relevant response content

            except AuthenticationError:
                logger.error("❌ OpenAI API Authentication failed. Check your API key.")
                return None

            except RateLimitError:
                logger.warning(f"⚠️ Rate limit exceeded. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                wait_time *= 2  # Exponential backoff
                attempt += 1

            except APIConnectionError:
                logger.error("❌ Failed to connect to OpenAI API. Check your internet connection.")
                return None

            except APITimeoutError:
                logger.warning("⚠️ OpenAI API request timed out. Retrying...")
                attempt += 1
                time.sleep(wait_time)

            except OpenAIError as e:
                logger.error(f"❌ OpenAI API error: {e}")
                return None

        logger.error("❌ Max retries reached. Skipping article.")
        return None

    def prepare_batch_file(self, articles: List[Dict[str, Any]]) -> Path:
        """Create JSONL file with batch requests."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        input_file = self.input_dir / f"batch_{timestamp}.jsonl"
        
        with input_file.open("w", encoding="utf-8") as f:
            for article in articles:
                request = self.create_batch_request(article)
                f.write(json.dumps(request.model_dump()) + "\n")  # Ensure valid JSON line format

        return input_file

    def upload_and_process(self, input_file: Path) -> Optional[Dict]:
        """Upload and process batch requests."""
        try:
            with input_file.open("rb") as f:
                file_upload = self.client.files.create(file=f, purpose="batch")

            batch = self.client.batches.create(
                input_file_id=file_upload.id,
                endpoint="/v1/chat/completions"
            )
            return {"batch_id": batch.id, "file_id": file_upload.id}

        except OpenAIError as e:
            logger.error(f"❌ OpenAI API error: {e}")
            return None

    def check_status(self, batch_id: str) -> Dict[str, Any]:
        """Check batch processing status."""
        return self.client.batches.retrieve(batch_id)

    def get_results(self, output_file_id: str) -> Optional[Path]:
        """Download and save batch results."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"results_{timestamp}.jsonl"

        try:
            response = self.client.files.content(output_file_id)
            output_file.write_text(response.content)
            return output_file
        except OpenAIError as e:
            logger.error(f"❌ Error retrieving OpenAI batch results: {e}")
            return None

    def process_articles(self, articles: List[Dict[str, Any]]) -> Optional[Path]:
        """Main method to process articles using OpenAI batch API."""
        try:
            input_file = self.prepare_batch_file(articles)
            logger.info(f"📄 Created batch file: {input_file}")

            batch_info = self.upload_and_process(input_file)
            if not batch_info:
                return None

            logger.info(f"📤 Uploaded batch file and created job: {batch_info['batch_id']}")

            while True:
                status = self.check_status(batch_info["batch_id"])
                logger.info(f"⏳ Batch status: {status.status}")

                if status.status == "completed":
                    results_file = self.get_results(status.output_file_id)
                    logger.info(f"✅ Batch completed. Results saved to: {results_file}")
                    return results_file

                elif status.status in ["failed", "expired"]:
                    logger.error(f"❌ Batch processing failed: {status.status}")
                    return None

                time.sleep(300)  # Check every 5 minutes

        except Exception as e:
            logger.error(f"❌ Batch processing error: {str(e)}")
            return None

def check_openai_usage():
    """Fetch and display OpenAI API usage."""
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        usage = client.usage.retrieve()
        total_tokens = usage["total_tokens"]

        logger.info(f"🔍 OpenAI Token Usage: {total_tokens} tokens used.")
        if total_tokens > 100_000:
            logger.warning("⚠️ WARNING: Over 100,000 tokens used. Check OpenAI account costs.")

    except Exception as e:
        logger.error(f"⚠️ Could not retrieve OpenAI usage stats: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_manager = DatabaseManager()
    processor = BatchProcessor()
    article_manager = ArticleManager(db_manager)
    articles = article_manager.get_articles()
    results = processor.process_articles(articles)

    if results:
        logger.info(f"✅ Batch processing completed. Results saved to: {results}")
