import os
import sys
import time
import asyncio
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List
from openai import OpenAI, RateLimitError

from src.logger_config import setup_logging
logger = setup_logging(__name__)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from src.database_manager import ArticleManager, DatabaseManager
from src.config import ConfigManager

class RateLimiter:
    def __init__(self, requests_per_minute: int):
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

class RatedArticle(BaseModel):
    """Structured output schema for processed articles."""
    raw_article_id: int
    url: str
    relevance_score: float

class ArticleProcessor:
    def __init__(self):
        config_manager = ConfigManager()
        self.OPENAI_API_KEY = config_manager.get("OPENAI_API_KEY")
        
        if not self.OPENAI_API_KEY:
            raise ValueError("Missing OpenAI API Key")
            
        self.client = OpenAI(api_key=self.OPENAI_API_KEY)
        requests_per_minute = config_manager.get("OPENAI_REQUESTS_PER_MINUTE", 60)
        self.rate_limiter = RateLimiter(requests_per_minute)
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

    async def process_article(self, article: Dict[str, Any], remaining_articles: int) -> Optional[Dict[str, Any]]:
        """Process a single article using the OpenAI API"""
        if not article:
            logger.error("Empty article provided")
            return None

        self.rate_limiter.wait_if_needed()

        try:
            async with self.semaphore:
                context_data = self.get_context_data(article)
                
                response = self.client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert in pharmaceutical security and supply chain integrity and all facets thereof. "
                                     "Analyze articles and rate their relevance to these topics from 0-1 where "
                                     "where 1 is highly relevant, 0.75 is moderately relevant, 0.5 is somewhat relevant, 0.25 is marginally relevant, and 0 is not relevant."
                        },
                        {
                            "role": "user",
                            "content": 
                                    f"Raw Article ID: {article.get('id', '')}\n"
                                    f"Title: {article.get('url', '')}\n"
                                    f"Content: {article.get('content', '')}"
                                    f"URL: {article.get('url', '')}"
                        }
                    ],
                    max_tokens=250,
                    temperature=0,
                    response_format=RatedArticle
                )

                if response.choices and response.choices[0].message:
                    parsed_response = response.choices[0].message.parsed
                    relevance_score = parsed_response.relevance_score

                    logger.info(f"Remaining articles to process: {remaining_articles}")
                    return {
                        'raw_article_id': article.get('id', 0),
                        'url': article.get('url', ''),
                        'relevance_score': relevance_score,
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
        total_articles = len(articles)
        
        for idx, article in enumerate(articles):
            remaining_articles = total_articles - idx - 1
            task = asyncio.create_task(self.process_article(article, remaining_articles))
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
    logging.basicConfig(level=logger.INFO)
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