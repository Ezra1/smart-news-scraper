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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
        self.batch_counter = 0
        self.batch_status = None
        self.completion_window = "24h"

    def _create_batch_request(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """Create a single batch request for an article."""
        return {
            "custom_id": f"article-{article.get('id')}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4-turbo-preview",
                "messages": [
                    {
                        "role": "system",
                        "content": "Evaluate article relevance and return a score from 0-1."
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Title: {article.get('title', '')}\n"
                            f"Content: {article.get('content', '')}"
                        )
                    }
                ],
                "max_tokens": 150,
                "temperature": 0
            }
        }

    def prepare_batch_file(self, articles: List[Dict[str, Any]]) -> str:
        """Create JSONL file for batch processing."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        input_file = self.input_dir / f"batch_input_{timestamp}.jsonl"
        
        with open(input_file, 'w', encoding='utf-8') as f:
            for article in articles:
                request = self._create_batch_request(article)
                f.write(json.dumps(request) + '\n')
        
        return str(input_file)

    async def create_batch(self, input_file: str) -> Optional[str]:
        """Create a new batch job with OpenAI."""
        try:
            response = await self.client.files.create(
                file=open(input_file, 'rb'),
                purpose="batch"
            )
            
            batch_response = await self.client.batches.create(
                input_file_id=response.id,
                endpoint="/v1/chat/completions",
                completion_window=self.completion_window
            )
            
            return batch_response.id
        except Exception as e:
            logger.error(f"Failed to create batch: {e}")
            return None

    async def check_batch_status(self, batch_id: str) -> Optional[Dict]:
        """Check the status of a batch job."""
        try:
            status = await self.client.batches.retrieve(batch_id)
            self.batch_status = status
            return status
        except Exception as e:
            logger.error(f"Failed to check batch status: {e}")
            return None

    async def process_articles(self, articles: List[Dict[str, Any]]) -> Optional[Path]:
        """Process articles using OpenAI's Batch API."""
        if not articles:
            logger.warning("No articles to process")
            return None

        try:
            # Prepare batch file
            input_file = self.prepare_batch_file(articles)
            logger.info(f"Created batch input file: {input_file}")

            # Create and submit batch
            batch_id = await self.create_batch(input_file)
            if not batch_id:
                raise Exception("Failed to create batch")

            # Monitor batch progress
            while True:
                status = await self.check_batch_status(batch_id)
                if not status:
                    raise Exception("Failed to check batch status")

                logger.info(f"Batch status: {status.status}")
                
                if status.status == "completed":
                    # Download and save results
                    output_file = self.output_dir / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
                    await self.client.files.download(status.output_file_id, output_file)
                    return output_file
                    
                elif status.status in ["failed", "expired", "cancelled"]:
                    raise Exception(f"Batch failed with status: {status.status}")

                await asyncio.sleep(60)  # Check every minute

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            return None

    def send_openai_request(self, article: Dict[str, Any], model: str = "gpt-4-turbo-preview") -> Optional[Dict]:
        """Legacy method for direct API calls - kept for fallback purposes."""
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

                if not response or not hasattr(response.choices[0].message, 'content'):
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