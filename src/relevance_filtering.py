"""src/relevance_filtering.py"""

import os
import sys
import time
import logging
import logging.config
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from multiprocessing import Pool, cpu_count
from functools import partial
from pydantic import BaseModel, ValidationError
from openai import OpenAI, OpenAIError, APIError, RateLimitError, APIConnectionError
import requests.exceptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.database import DatabaseManager, ArticleManager

# Custom exceptions
class BatchProcessingError(Exception):
    """Base exception for batch processing errors"""
    pass

class ConfigurationError(BatchProcessingError):
    """Raised when there are configuration-related errors"""
    pass

class FileOperationError(BatchProcessingError):
    """Raised when file operations fail"""
    pass

class OpenAIBatchError(BatchProcessingError):
    """Raised when OpenAI batch operations fail"""
    pass

class DatabaseError(BatchProcessingError):
    """Raised when database operations fail"""
    pass

class BatchProcessor:
    """Handles batch processing of articles for relevance scoring."""

    RELEVANCE_THRESHOLD = 0.7
    BATCH_INPUT_PATH = Path("openAIFiles/input/batch_input.jsonl")
    MAX_RETRIES = 3
    RETRY_DELAY = 5

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ConfigurationError("OPENAI_API_KEY not set")
            
            self.client = OpenAI(api_key=api_key)
            self.db_manager = db_manager or DatabaseManager()
            self.article_manager = ArticleManager(self.db_manager)
            self.max_workers = min(32, cpu_count() * 2)
            
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize BatchProcessor: {str(e)}")

    def get_articles(self) -> List[Dict[str, Any]]:
        """Get articles from database."""
        try:
            articles = self.article_manager.get_articles()
            if not articles:
                raise DatabaseError("No articles found")
            return articles
        except Exception as e:
            raise DatabaseError(f"Failed to retrieve articles: {str(e)}")

    @staticmethod
    def _process_single_article(client, article: Dict) -> Optional[Dict]:
        """Process a single article."""
        try:
            prompt = (
                "Please evaluate the relevance of the article below to the topics 'pharmaceutical security', "
                "'regulatory compliance', 'international law enforcement coordination', 'data analysis for tracking "
                "counterfeit products', and 'the development of anti-counterfeiting strategies'.\n\n"
                "Return a JSON object containing:\n"
                "- 'id': The ID for the article\n"
                "- 'title': The title of the article\n"
                "- 'relevance_score': A relevance score from 0 (completely irrelevant) to 1 (highly relevant)\n\n"
                f"Article Title: '{article.get('title', '')}'\n\n"
                f"Article Content: {article.get('content', '')}\n\n"
            )

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Return the relevance score and title as a JSON object."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.0
            )
            
            return {
                "custom_id": f"article-{article['id']}",
                "response": response.model_dump()
            }
        except Exception as e:
            logging.error(f"Error processing article {article.get('id')}: {e}")
            return None

    def process_batch_parallel(self, articles: List[Dict]) -> None:
        """Process articles in parallel."""
        with Pool(self.max_workers) as pool:
            process_func = partial(self._process_single_article, self.client)
            results = pool.map(process_func, articles)
            
        valid_results = [r for r in results if r]
        self._write_batch_results(valid_results)

    def _write_batch_results(self, results: List[Dict]) -> None:
        """Write batch results to JSONL file."""
        self.BATCH_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.BATCH_INPUT_PATH, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

    def upload_batch_file(self) -> str:
        """Upload batch file to OpenAI."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with open(self.BATCH_INPUT_PATH, "rb") as file:
                    response = self.client.files.create(file=file, purpose="batch")
                    logging.info(f"Batch file uploaded. ID: {response.id}")
                    return response.id
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OpenAIBatchError(f"Failed to upload batch file: {str(e)}")
                time.sleep(self.RETRY_DELAY * (attempt + 1))

    def create_batch_job(self, file_id: str) -> str:
        """Create OpenAI batch job."""
        for attempt in range(self.MAX_RETRIES):
            try:
                batch = self.client.batches.create(
                    input_file_id=file_id,
                    endpoint="/v1/chat/completions",
                    completion_window="24h"
                )
                logging.info(f"Batch job created. ID: {batch.id}")
                return batch.id
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OpenAIBatchError(f"Failed to create batch job: {str(e)}")
                time.sleep(self.RETRY_DELAY * (attempt + 1))

    def check_batch_status(self, batch_id: str) -> Optional[Path]:
        """Monitor batch job status."""
        try:
            output_dir = Path("openAIFiles/output")
            output_dir.mkdir(parents=True, exist_ok=True)
            max_wait_time = 24 * 60 * 60

            start_time = time.time()
            while time.time() - start_time < max_wait_time:
                batch_status = self.client.batches.retrieve(batch_id)
                
                if batch_status.status == "completed":
                    output_file_id = batch_status.output_file.id
                    output_path = output_dir / f"batch_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
                    
                    file_response = self.client.files.content(output_file_id)
                    output_path.write_text(file_response.text, encoding="utf-8")
                    return output_path
                
                if batch_status.status in ["failed", "expired"]:
                    raise OpenAIBatchError(f"Batch job {batch_id} {batch_status.status}")
                
                time.sleep(300)  # Check every 5 minutes
                
            raise OpenAIBatchError(f"Batch job {batch_id} timed out")
            
        except Exception as e:
            raise OpenAIBatchError(f"Error checking batch status: {str(e)}")

    def process_batch(self) -> Optional[Path]:
        """Main batch processing method."""
        try:
            articles = self.get_articles()
            self.process_batch_parallel(articles)
            file_id = self.upload_batch_file()
            batch_id = self.create_batch_job(file_id)
            return self.check_batch_status(batch_id)
            
        except BatchProcessingError as e:
            logging.error(f"Batch processing error: {str(e)}")
            raise
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            raise BatchProcessingError(f"Failed to complete batch processing: {str(e)}")

if __name__ == "__main__":
    try:
        current_directory = os.path.dirname(os.path.abspath(__file__))
        logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')
        logging.config.fileConfig(logging_config_path)
        load_dotenv()

        db_manager = DatabaseManager()
        processor = BatchProcessor(db_manager)
        results = processor.process_batch()
        
        if results:
            logging.info(f"Batch processing completed. Results saved to: {results}")
        sys.exit(0)
        
    except Exception as e:
        logging.critical(f"Critical error: {str(e)}")
        sys.exit(1)