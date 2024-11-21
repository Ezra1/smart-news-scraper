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
from pydantic import BaseModel, ValidationError
from openai import OpenAI, OpenAIError, APIError, RateLimitError, APIConnectionError
import requests.exceptions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.database import DatabaseManager, ArticleManager

# Custom exceptions for better error handling
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
    """Handles the creation, uploading, and processing of batch jobs for article relevance scoring."""

    RELEVANCE_THRESHOLD = 0.7
    BATCH_INPUT_PATH = Path("openAIFiles/input/batch_input.jsonl")
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        try:
            # Initialize OpenAI client with the API key from the environment
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ConfigurationError("OPENAI_API_KEY is not set in environment variables")
            
            self.client = OpenAI(api_key=api_key)
            self.db_manager = db_manager or DatabaseManager()
            self.article_manager = ArticleManager(self.db_manager)
            
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize BatchProcessor: {str(e)}")
    
    class RelevanceResponse(BaseModel):
        """Schema for the relevance response"""
        id: str
        title: str
        relevance_score: float

    def get_articles(self) -> List[Dict[str, Any]]:
        """Get articles from the database with error handling."""
        try:
            articles = self.article_manager.get_articles()
            if not articles:
                raise DatabaseError("No articles found in the database")
            return articles
        except Exception as e:
            raise DatabaseError(f"Failed to retrieve articles from database: {str(e)}")

    def create_jsonl_for_batch(self, articles: List[Dict[str, Any]]) -> None:
        """Generate a JSONL file for batch relevance scoring with enhanced error handling."""
        try:
            self.BATCH_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            logging.info("Storing batch input json in: %s", self.BATCH_INPUT_PATH)

            with open(self.BATCH_INPUT_PATH, "w", encoding="utf-8") as jsonl_file:
                for article in articles:
                    try:
                        article_id = article["id"]
                        title = article["title"]
                        content = article.get("content", "")
                        
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
                                "model": "gpt-4",
                                "messages": [
                                    {"role": "system", "content": "Return the relevance score and title as a JSON object."},
                                    {"role": "user", "content": prompt}
                                ],
                                "max_tokens": 150,
                                "temperature": 0.0
                            }
                        }
                        jsonl_file.write(json.dumps(json_line) + "\n")
                    except KeyError as ke:
                        logging.error("Missing required field in article data: %s", ke)
                        continue
                    except json.JSONEncodeError as je:
                        logging.error("Failed to encode article data to JSON: %s", je)
                        continue
                    
        except IOError as e:
            raise FileOperationError(f"Failed to create JSONL file: {str(e)}")
        except Exception as e:
            raise FileOperationError(f"Unexpected error while creating JSONL file: {str(e)}")
        
        logging.info("JSONL file created successfully.")

    def upload_jsonl_file(self) -> str:
        """Upload the JSONL file with retries and detailed error handling."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with open(self.BATCH_INPUT_PATH, "rb") as file:
                    response = self.client.files.create(file=file, purpose="batch")
                    logging.info("Batch file uploaded successfully. File ID: %s", response.id)
                    return response.id
                    
            except FileNotFoundError:
                raise FileOperationError(f"JSONL file not found at {self.BATCH_INPUT_PATH}")
            except RateLimitError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OpenAIBatchError(f"Rate limit exceeded after {self.MAX_RETRIES} attempts: {str(e)}")
                time.sleep(self.RETRY_DELAY * (attempt + 1))
            except APIConnectionError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OpenAIBatchError(f"Failed to connect to OpenAI API: {str(e)}")
                time.sleep(self.RETRY_DELAY)
            except APIError as e:
                raise OpenAIBatchError(f"OpenAI API error: {str(e)}")
            except Exception as e:
                raise OpenAIBatchError(f"Unexpected error during file upload: {str(e)}")

    def create_batch_job(self, file_id: str) -> str:
        """Create a batch job with retry logic and specific error handling."""
        for attempt in range(self.MAX_RETRIES):
            try:
                batch = self.client.batches.create(
                    input_file_id=file_id,
                    endpoint="/v1/chat/completions",
                    completion_window="24h",
                    metadata={"description": "Batch relevance scoring for articles"}
                )
                logging.info("Batch job created with ID: %s", batch.id)
                return batch.id
                
            except RateLimitError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OpenAIBatchError(f"Rate limit exceeded when creating batch job: {str(e)}")
                time.sleep(self.RETRY_DELAY * (attempt + 1))
            except APIConnectionError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise OpenAIBatchError(f"Connection error when creating batch job: {str(e)}")
                time.sleep(self.RETRY_DELAY)
            except APIError as e:
                raise OpenAIBatchError(f"OpenAI API error during batch creation: {str(e)}")
            except Exception as e:
                raise OpenAIBatchError(f"Unexpected error during batch creation: {str(e)}")

    def check_batch_status(self, batch_id: str) -> Optional[Path]:
        """Check batch status with improved error handling and timeout mechanism."""
        try:
            output_dir = Path("openAIFiles/output")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            start_time = time.time()
            max_wait_time = 24 * 60 * 60  # 24 hours in seconds

            while time.time() - start_time < max_wait_time:
                try:
                    batch_status = self.client.batches.retrieve(batch_id)
                    
                    if batch_status.status == "completed":
                        output_file_id = batch_status.output_file_id
                        output_file_path = output_dir / f"batch_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
                        
                        try:
                            file_response = self.client.files.content(output_file_id)
                            output_file_path.write_text(file_response.text, encoding="utf-8")
                            logging.info("Output file %s created successfully.", output_file_path)
                            return output_file_path
                        except (IOError, APIError) as e:
                            raise FileOperationError(f"Failed to write output file: {str(e)}")
                    
                    if batch_status.status in ["failed", "expired"]:
                        raise OpenAIBatchError(f"Batch job {batch_id} {batch_status.status}")
                    
                    logging.info("Batch job %s in progress... Checking again in 5 minutes.", batch_id)
                    time.sleep(300)
                    
                except APIConnectionError as e:
                    logging.warning("Temporary connection error, retrying: %s", str(e))
                    time.sleep(self.RETRY_DELAY)
                    continue
                    
            raise OpenAIBatchError(f"Batch job {batch_id} timed out after 24 hours")
            
        except Exception as e:
            raise OpenAIBatchError(f"Error checking batch status: {str(e)}")

    def process_batch(self) -> Optional[Path]:
        """Main batch processing method with comprehensive error handling."""
        try:
            articles = self.get_articles()
            self.create_jsonl_for_batch(articles)
            file_id = self.upload_jsonl_file()
            batch_id = self.create_batch_job(file_id)
            results_path = self.check_batch_status(batch_id)
            
            if results_path:
                logging.info("Batch processing completed successfully.")
                return results_path
                
        except BatchProcessingError as e:
            logging.error("Batch processing error: %s", str(e))
            raise
        except Exception as e:
            logging.error("Unexpected error in batch processing: %s", str(e))
            raise BatchProcessingError(f"Failed to complete batch processing: {str(e)}")

if __name__ == "__main__":
    try:
        # Set up logging
        current_directory = os.path.dirname(os.path.abspath(__file__))
        logging_config_path = os.path.join(current_directory, '..', 'config', 'logging.conf')
        logging.config.fileConfig(logging_config_path)
        logger = logging.getLogger(__name__)
        load_dotenv()

        db_manager = DatabaseManager()
        batch_processor = BatchProcessor(db_manager)
        results = batch_processor.process_batch()
        
        if results:
            logging.info("Batch processing completed successfully. Results saved to: %s", results)
        sys.exit(0)
        
    except ConfigurationError as e:
        logging.critical("Configuration error: %s", str(e))
        sys.exit(1)
    except DatabaseError as e:
        logging.critical("Database error: %s", str(e))
        sys.exit(1)
    except FileOperationError as e:
        logging.critical("File operation error: %s", str(e))
        sys.exit(1)
    except OpenAIBatchError as e:
        logging.critical("OpenAI batch processing error: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logging.critical("Unexpected error: %s", str(e))
        sys.exit(1)