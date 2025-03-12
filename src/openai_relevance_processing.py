import os
import sys
import time
import asyncio
import logging  # Add this import for logging
from pydantic import BaseModel
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
    def __init__(self, db_manager: DatabaseManager = None):
        config_manager = ConfigManager()
        self.OPENAI_API_KEY = config_manager.get("OPENAI_API_KEY")
        
        if not self.OPENAI_API_KEY:
            raise ValueError("Missing OpenAI API Key")
            
        self.client = OpenAI(api_key=self.OPENAI_API_KEY)
        requests_per_minute = config_manager.get("OPENAI_REQUESTS_PER_MINUTE", 60)
        self.rate_limiter = RateLimiter(requests_per_minute)
        self.semaphore = asyncio.Semaphore(5)  # Limit concurrent requests
        
        # Initialize tracking variables
        self.total_relevant = 0
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0.0
        self.RELEVANCE_THRESHOLD = config_manager.get("RELEVANCE_THRESHOLD")
        logger.info(f"Initialized ArticleProcessor with relevance threshold: {self.RELEVANCE_THRESHOLD}")
        
        # Use provided database manager or create new one
        self.db_manager = db_manager or DatabaseManager()
        self.article_manager = ArticleManager(self.db_manager)
        
        # Add batch size configuration
        self.batch_size = config_manager.get("BATCH_SIZE", 10)

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
        """Process a single article using the OpenAI API and store relevant results in the database"""
        if not article:
            logger.error("Empty article provided")
            return

        self.rate_limiter.wait_if_needed()

        try:
            async with self.semaphore:
                # Process article through OpenAI API
                """{
                            "role": "system",
                            "content": "You are an expert in pharmaceutical security and supply chain integrity and all facets thereof."
                                    "Analyze articles and rate their relevance to these topics from 0-1 where "
                                    "where 1 is highly relevant, around 0.7 is moderately relevant, below 0.5 is less and less relevant, and 0 is not relevant at all."
                    }"""
                context_data = self.get_context_data(article)
                
                response = self.client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert in the geopolitics, specifically in Saudi Arabia and Kuwait."
                                    "Analyze articles and rate their relevance to anything that has the potential to change the balance of power in the middle east regarding Saudi Arabia and Kuwait or "
                                    "Saudi Arabia and Kuwait's capabilities in the military or industrial sphere from 0-1 where"
                                    "where 1 is highly relevant, around 0.7 is moderately relevant, below 0.5 is less and less relevant, and 0 is not relevant at all."
                        },
                        {
                            "role": "user",
                            "content": 
                                    f"Raw Article ID: {article.get('id', '')}\n"
                                    f"Title: {article.get('title', '')}\n"
                                    f"Content: {article.get('content', '')}\n"
                                    f"URL: {article.get('url', '')}"
                        }
                    ],
                    max_tokens=250,
                    temperature=0,
                    response_format=RatedArticle
                )

                if not response.choices or not response.choices[0].message:
                    logger.error(f"No response received for article ID: {article.get('id', '')}")
                    return

                # Extract relevance score from response
                parsed_response = response.choices[0].message.parsed
                relevance_score = parsed_response.relevance_score
                raw_article_id = article.get('id')
                url = article.get('url')

                logger.info(f"Processing article - ID: {raw_article_id}, URL: {url}, Score: {relevance_score}")
                logger.info(f"RELEVANCE_THRESHOLD: {self.RELEVANCE_THRESHOLD}")

                # Process and store relevant articles
                if relevance_score >= self.RELEVANCE_THRESHOLD:
                    logger.info(f"Article with ID '{raw_article_id}' is relevant (score: {relevance_score})")
                    self.total_relevant += 1
                    self.relevant += 1  # Increment relevant count
                    self.max_relevance_score = max(self.max_relevance_score, relevance_score)

                    # Insert the article data into the cleaned_articles table
                    self.article_manager.insert_cleaned_article(
                        raw_article_id=raw_article_id,
                        title=article.get('title'),
                        content=article.get('content'),
                        source=article.get('source'),
                        url=url,
                        url_to_image=article.get('url_to_image'),
                        published_at=article.get('published_at'),
                        relevance_score=relevance_score
                    )
                    logger.info(f"✅ Inserted relevant article '{article.get('title')}' with score {relevance_score}")
                else:
                    self.irrelevant += 1
                    logger.info(f"❌ Article with ID '{raw_article_id}' is not relevant (score: {relevance_score})")

                logger.info(f"Total relevant articles: {self.total_relevant}")
                logger.info(f"Remaining articles to process: {remaining_articles}")

        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded: {e}")
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error processing article ID {article.get('id', '')}: {e}")

    async def process_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process articles in optimized batches"""
        results = []
        for i in range(0, len(articles), self.batch_size):
            batch = articles[i:i + self.batch_size]
            tasks = [
                self.process_article(article, len(articles) - i - idx)
                for idx, article in enumerate(batch)
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            results.extend([r for r in batch_results if not isinstance(r, Exception)])
            
        return results
    
    def analyze_results(self):
        """Analyze the results after processing output."""
        total_articles = self.relevant + self.irrelevant
        if total_articles == 0:
            logger.warning("⚠️ No articles processed.")
            return

        relevant_percentage = (self.relevant / total_articles) * 100
        irrelevant_percentage = (self.irrelevant / total_articles) * 100
        ratio = self.relevant / self.irrelevant if self.irrelevant > 0 else float('inf')

        analysis_results = {
            "Relevant articles": self.relevant,
            "Irrelevant articles": self.irrelevant,
            "Total articles": total_articles,
            "Relevant percentage": f"{relevant_percentage:.2f}%",
            "Irrelevant percentage": f"{irrelevant_percentage:.2f}%",
            "Relevance ratio": f"{ratio:.2f}",
            "Max relevance score": self.max_relevance_score
        }

        # Log and print results
        for key, value in analysis_results.items():
            logger.info(f"{key}: {value}")
            print(f"{key}: {value}")

        # Analysis conclusion
        conclusion = (
            "✅ Most articles are relevant, indicating well-targeted search."
            if relevant_percentage > 50
            else "⚠️ Most articles are irrelevant, suggesting search criteria refinement needed."
        )
        logger.info(conclusion)
        print(conclusion)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)  # Fix logging setup
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

