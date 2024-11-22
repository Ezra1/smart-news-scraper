import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from openai import OpenAI
from pydantic import BaseModel, Field

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from src.database import ArticleManager, DatabaseManager  # Import your database access method

class BatchRequest(BaseModel):
    custom_id: str
    method: str = "POST"
    url: str = "/v1/chat/completions"
    body: Dict[str, Any]

class BatchError(Exception):
    """Base exception for batch processing errors"""
    pass

class BatchProcessor:
    """Handles batch processing using OpenAI's Batch API"""
    
    def __init__(self):
        OPEN_API_KEY = os.getenv("OPENAI_API_KEY")
        OpenAI.api_key = OPEN_API_KEY
        self.client = OpenAI()
        self.input_dir = Path("batch/input")
        self.output_dir = Path("batch/output")
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_batch_request(self, article: Dict[str, Any], model: str = "gpt-4o-mini") -> BatchRequest:
        """Create a batch request for one article."""
        prompt = (
            "Evaluate the article's relevance to pharmaceutical security, regulatory compliance, "
            "and anti-counterfeiting strategies.\n\n"
            f"Title: {article.get('title', '')}\n"
            f"Content: {article.get('content', '')}"
        )

        return BatchRequest(
            custom_id=f"article-{article['id']}",
            body={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Evaluate article relevance and return a score from 0-1."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 150,
                "temperature": 0
            }
        )

    def prepare_batch_file(self, articles: List[Dict[str, Any]]) -> Path:
        """Create JSONL file with batch requests."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        input_file = self.input_dir / f"batch_{timestamp}.jsonl"
        
        with input_file.open("w", encoding="utf-8") as f:
            for article in articles:
                request = self.create_batch_request(article)
                # Ensure each line is valid JSON and add a newline
                f.write(json.dumps(request.model_dump()) + "\n")

        print()
        
        return input_file

    def upload_and_process(self, input_file: Path) -> Dict[str, str]:
        """Upload file and create batch job."""
        try:
            # Verify file exists and has .jsonl extension
            if not input_file.exists():
                raise BatchError(f"Input file not found: {input_file}")
            
            if input_file.suffix != '.jsonl':
                raise BatchError(f"Input file must have .jsonl extension, got: {input_file}")
            
            # Upload file
            with input_file.open("rb") as f:
                file_upload = self.client.files.create(
                    file=f,
                    purpose="batch"  # or whatever purpose is appropriate for batch processing
                )

            # Create batch
            batch = self.client.batches.create(
                input_file_id=file_upload.id,
                endpoint="/v1/chat/completions"
            )

            return {
                "batch_id": batch.id,
                "file_id": file_upload.id
            }
            
        except Exception as e:
            raise BatchError(f"Error in upload_and_process: {str(e)}")

    def check_status(self, batch_id: str) -> Dict[str, Any]:
        """Check batch processing status."""
        return self.client.batches.retrieve(batch_id)

    def get_results(self, output_file_id: str) -> Path:
        """Download and save batch results."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"results_{timestamp}.jsonl"
        
        response = self.client.files.content(output_file_id)
        output_file.write_text(response.content)
        
        return output_file

    def process_articles(self, articles: List[Dict[str, Any]]) -> Optional[Path]:
        """Main method to process articles using batch API."""
        try:
            # Prepare and upload batch file
            input_file = self.prepare_batch_file(articles)
            logging.info(f"Created batch file: {input_file}")
            
            batch_info = self.upload_and_process(input_file)
            logging.info(f"Uploaded batch file and created job: {batch_info['batch_id']}")
            
            # Monitor status
            while True:
                status = self.check_status(batch_info["batch_id"])
                logging.info(f"Batch status: {status.status}")
                
                if status.status == "completed":
                    results_file = self.get_results(status.output_file_id)
                    logging.info(f"Batch completed. Results saved to: {results_file}")
                    return results_file
                elif status.status in ["failed", "expired"]:
                    raise BatchError(f"Batch {batch_info['batch_id']} {status.status}")
                
                time.sleep(300)  # Check every 5 minutes
                
        except Exception as e:
            logging.error(f"Batch processing error: {str(e)}")
            raise BatchError(str(e))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_manager = DatabaseManager()
    processor = BatchProcessor()
    article_manager = ArticleManager(db_manager)
    articles = article_manager.get_articles()
    results = processor.process_articles(articles)
    
    if results:
        logging.info(f"Batch processing completed. Results saved to: {results}")