import os
import sys
import logging
import time
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from openai import OpenAI
from openai import OpenAIError, RateLimitError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from database import ArticleManager, DatabaseManager
from config import ConfigManager

class RateLimiter:
    def __init__(self, requests_per_minute: int = 120):
        self.requests_per_minute = requests_per_minute
        self.request_times = []
        self._last_request_time = 0

    def wait_if_needed(self):
        """Implement rate limiting based on requests per minute."""
        current_time = time.time()
        
        # Clean up old request times
        self.request_times = [t for t in self.request_times if current_time - t < 120]
        
        # Check if we need to wait
        if len(self.request_times) >= self.requests_per_minute:
            wait_time = 120 - (current_time - self.request_times[0])
            if wait_time > 0:
                time.sleep(wait_time)
        
        # Ensure minimum time between requests
        time_since_last_request = current_time - self._last_request_time
        if time_since_last_request < 1.0:
            time.sleep(1.0 - time_since_last_request)
        
        # Update tracking
        self._last_request_time = time.time()
        self.request_times.append(self._last_request_time)

class ArticleProcessor:
    def __init__(self):
        config_manager = ConfigManager()
        self.OPENAI_API_KEY = config_manager.get("OPENAI_API_KEY")
        
        if not self.OPENAI_API_KEY:
            raise ValueError("Missing OpenAI API Key")
            
        self.client = OpenAI(api_key=self.OPENAI_API_KEY)
        self.rate_limiter = RateLimiter()
        self.semaphore = asyncio.Semaphore(5)  # Limit concurrent requests

    def get_context_data(self, article: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve relevant context data for the article."""
        # This would be your RAG implementation
        # For example, getting similar articles or relevant domain knowledge
        return [
            {
                "type": "text",
                "text": "Context: This analysis focuses on pharmaceutical security and supply chain integrity."
            },
            {
                "type": "text",
                "text": f"Article Title: {article.get('title', '')}"
            },
            {
                "type": "text",
                "text": f"Article Content: {article.get('content', '')}"
            }
        ]

    async def process_article(self, article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single article using the OpenAI API with RAG."""
        if not article:
            logger.error("Empty article provided")
            return None

        self.rate_limiter.wait_if_needed()

        try:
            async with self.semaphore:
                context_data = self.get_context_data(article)
                
                # Remove await since OpenAI's create is synchronous
                response = self.client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert in pharmaceutical security and supply chain integrity. "
                                     "Analyze articles and rate their relevance to these topics."
                        },
                        {
                            "role": "user",
                            "content": f"Title: {article.get('title', '')}\n"
                                     f"Content: {article.get('content', '')}"
                        }
                    ],
                    max_tokens=250,
                    temperature=0
                )

                if response.choices and response.choices[0].message:
                    return {
                        'article_id': article.get('id'),
                        'analysis': response.choices[0].message.content,
                        'processed_at': datetime.now().isoformat()
                    }
                
                return None

        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded: {e}")
            await asyncio.sleep(10)
            return None
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None

    async def process_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process multiple articles concurrently with rate limiting."""
        tasks = []
        results = []
        
        for article in articles:
            task = asyncio.create_task(self.process_article(article))
            tasks.append(task)
        
        for idx, task in enumerate(asyncio.as_completed(tasks), 1):
            try:
                result = await task
                if result:
                    results.append(result)
                    logger.info(f"Successfully processed article {idx}")
                else:
                    logger.error(f"Failed to process article {idx}")
            except Exception as e:
                logger.error(f"Error processing article {idx}: {e}")
                
        return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        db_manager = DatabaseManager()
        processor = ArticleProcessor()
        article_manager = ArticleManager(db_manager)
        articles = article_manager.get_articles()
        
        # Run async processing
        results = asyncio.run(processor.process_articles(articles))

        if results:
            logger.info(f"Processing completed. Processed {len(results)} articles.")
        else:
            logger.error("Processing failed")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        db_manager.close()