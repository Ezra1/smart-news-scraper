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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from database import ArticleManager, DatabaseManager
from config import ConfigManager

class BatchRequest(BaseModel):
    custom_id: str
    method: str = "POST"
    url: str = "/v1/chat/completions"
    body: Dict[str, Any]

class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.request_times = []
        self._last_request_time = 0

    def wait_if_needed(self):
        """Implement rate limiting based on requests per minute."""
        current_time = time.time()
        
        # Clean up old request times
        self.request_times = [t for t in self.request_times if current_time - t < 60]
        
        # Check if we need to wait
        if len(self.request_times) >= self.requests_per_minute:
            wait_time = 60 - (current_time - self.request_times[0])
            if wait_time > 0:
                time.sleep(wait_time)
        
        # Ensure minimum time between requests
        time_since_last_request = current_time - self._last_request_time
        if time_since_last_request < 1.0:
            time.sleep(1.0 - time_since_last_request)
        
        # Update tracking
        self._last_request_time = time.time()
        self.request_times.append(self._last_request_time)

class BatchProcessor:
    def __init__(self):
        config_manager = ConfigManager()
        self.OPENAI_API_KEY = config_manager.get("OPENAI_API_KEY")
        
        if not self.OPENAI_API_KEY:
            raise ValueError("Missing OpenAI API Key")
            
        OpenAI.api_key = self.OPENAI_API_KEY
        self.client = OpenAI()
        self.input_dir = Path("batch/input")
        self.output_dir = Path("batch/output")
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limiter = RateLimiter()

    def send_openai_request(self, article: Dict[str, Any], model: str = "gpt-4-turbo-preview") -> Optional[Dict]:
        """Send an article for processing with rate limiting and enhanced error handling."""
        if not article:
            logger.error("Empty article provided")
            return None

        # Apply rate limiting
        self.rate_limiter.wait_if_needed()

        attempt = 0
        max_attempts = 5
        base_wait_time = 5

        while attempt < max_attempts:
            try:
                prompt = (
                    "Evaluate the article's relevance to pharmaceutical security, regulatory compliance, "
                    "and anti-counterfeiting strategies.\n\n"
                    f"Title: {article.get('title', '')}\n"
                    f"Content: {article.get('content', '')}"
                )

                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Evaluate article relevance and return a score from 0-1."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=150,
                    temperature=0
                )

                if not response or not hasattr(response, 'choices'):
                    logger.error("Invalid API response format")
                    return None

                return response.choices[0].message.content

            except RateLimitError:
                wait_time = base_wait_time * (2 ** attempt)
                logger.warning(f"Rate limit exceeded. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                attempt += 1

            except (APIConnectionError, APITimeoutError):
                wait_time = base_wait_time * (2 ** attempt)
                logger.warning(f"API connection error. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                attempt += 1

            except AuthenticationError:
                logger.error("Authentication failed. Check API key.")
                return None

            except OpenAIError as e:
                logger.error(f"OpenAI API error: {e}")
                return None

        logger.error("Max retries reached")
        return None

    def _process_batch(self, batch: List[Dict[str, Any]]) -> Optional[Path]:
        """Process a single batch of articles."""
        try:
            input_file = self.prepare_batch_file(batch)
            if not input_file:
                return None

            logger.info(f"Processing batch of {len(batch)} articles")
            batch_info = self.upload_and_process(input_file)
            
            if not batch_info:
                return None

            while True:
                status = self.check_status(batch_info["batch_id"])
                logger.info(f"Batch status: {status.status}")

                if status.status == "completed":
                    return self.get_results(status.output_file_id)
                elif status.status in ["failed", "expired"]:
                    logger.error(f"Batch failed with status: {status.status}")
                    return None

                time.sleep(60)  # Check every minute

        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            return None

    def process_articles(self, articles: List[Dict[str, Any]]) -> Optional[Path]:
        """Process articles in batches with enhanced error handling."""
        if not articles:
            logger.warning("No articles to process")
            return None

        try:
            batch_size = 100
            results_files = []

            for i in range(0, len(articles), batch_size):
                batch = articles[i:i + batch_size]
                logger.info(f"Processing batch {i//batch_size + 1} of {(len(articles)-1)//batch_size + 1}")
                
                result_file = self._process_batch(batch)
                if result_file:
                    results_files.append(result_file)
                else:
                    logger.error(f"Failed to process batch {i//batch_size + 1}")

            if not results_files:
                logger.error("All batches failed")
                return None

            # Combine results if multiple batches
            if len(results_files) > 1:
                return self._combine_result_files(results_files)
            
            return results_files[0]

        except Exception as e:
            logger.error(f"Article processing failed: {e}")
            raise

    def _combine_result_files(self, files: List[Path]) -> Path:
        """Combine multiple result files into one."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_file = self.output_dir / f"combined_results_{timestamp}.jsonl"
        
        try:
            with combined_file.open('w') as outfile:
                for file in files:
                    with file.open('r') as infile:
                        outfile.write(infile.read())
            return combined_file
        except Exception as e:
            logger.error(f"Error combining result files: {e}")
            return files[0]  # Return first file if combination fails

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        db_manager = DatabaseManager()
        processor = BatchProcessor()
        article_manager = ArticleManager(db_manager)
        articles = article_manager.get_articles()
        results = processor.process_articles(articles)

        if results:
            logger.info(f"Batch processing completed. Results saved to: {results}")
        else:
            logger.error("Batch processing failed")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)