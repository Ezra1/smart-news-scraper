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
from src.analysis_base import ArticleAnalysisMixin
from src.utils.rate_limiter import RateLimiter

class RatedArticle(BaseModel):
    """Structured output schema for processed articles."""
    raw_article_id: int
    url: str
    relevance_score: float

class ArticleProcessor(ArticleAnalysisMixin):
    def __init__(self, db_manager: DatabaseManager = None, 
                 context_message: dict = None,
                 config_manager: ConfigManager = None):
        super().__init__()  # Initialize analysis mixin
        self.config_manager = config_manager or ConfigManager()
        self.OPENAI_API_KEY = self.config_manager.get("OPENAI_API_KEY")
        
        if not self.OPENAI_API_KEY:
            logger.error("Missing OpenAI API Key in configuration")
            raise ValueError("OpenAI API Key is required. Please configure it in the Configuration tab.")
        
        self.client = OpenAI(api_key=self.OPENAI_API_KEY)
        requests_per_minute = self.config_manager.get("OPENAI_REQUESTS_PER_MINUTE", 60)
        self.rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
        self.semaphore = asyncio.Semaphore(5)  # Limit concurrent requests
        
        # Initialize tracking variables
        self.total_relevant = 0
        self.relevant = 0
        self.irrelevant = 0
        self.max_relevance_score = 0.0
        self.RELEVANCE_THRESHOLD = self.config_manager.get("RELEVANCE_THRESHOLD")
        logger.info(f"Initialized ArticleProcessor with relevance threshold: {self.RELEVANCE_THRESHOLD}")
        
        # Use provided database manager or create new one
        self.db_manager = db_manager or DatabaseManager()
        self.article_manager = ArticleManager(self.db_manager)
        
        # Add batch size configuration
        self.batch_size = self.config_manager.get("BATCH_SIZE", 10)
        
        # Store context message
        self.context_message = context_message or self.config_manager.get("CHATGPT_CONTEXT_MESSAGE")

    def get_context_data(self, article: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve relevant context data for the article.
        
        This is a placeholder for a future RAG (Retrieval-Augmented Generation) implementation.
        Currently returns basic article information formatted for the OpenAI API.
        
        Args:
            article: Dictionary containing article data
            
        Returns:
            List of context data dictionaries formatted for OpenAI API
        """
        # Basic implementation - in a real RAG system, this would retrieve similar articles
        # or domain-specific knowledge to enhance the context
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

    async def process_article(self, article: Dict[str, Any], remaining: int) -> Optional[Dict[str, Any]]:
        """Process a single article"""
        try:
            article_id = article.get('id')
            source = article.get('source', 'Unknown Source')  # Add default source
            if isinstance(source, dict):
                source = source.get('name', 'Unknown Source')
                
            logger.info(f"Processing article - ID: {article_id}, URL: {article.get('url', 'No URL')}")
            
            # Get existing processing result if available
            if article_id:
                existing = self.db_manager.execute_query(
                    "SELECT relevance_score FROM relevant_articles WHERE raw_article_id = ?", 
                    (article_id,)
                )
                if existing:
                    logger.info(f"Using existing relevance score for article {article_id}")
                    article['relevance_score'] = existing[0]['relevance_score']
                    return article
            
            # Continue with regular processing
            logger.info(f"RELEVANCE_THRESHOLD: {self.RELEVANCE_THRESHOLD}")
            self.rate_limiter.wait_if_needed()

            try:
                async with self.semaphore:
                    # Get context data for RAG (if implemented)
                    context_data = self.get_context_data(article)
                    
                    # Process article through OpenAI API
                    response = self.client.beta.chat.completions.parse(
                        model="gpt-4o-mini",
                        messages=[
                            self.context_message,
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

                        # Insert the article data into the relevant_articles table
                        self.article_manager.insert_relevant_article(
                            raw_article_id=raw_article_id,
                            title=article.get('title', ''),
                            content=article.get('content', ''),
                            source=source,  # Use processed source
                            url=url,
                            url_to_image=article.get('url_to_image', ''),
                            published_at=article.get('published_at', ''),
                            relevance_score=relevance_score
                        )
                        logger.info(f"✅ Inserted relevant article '{article.get('title')}' with score {relevance_score}")
                    else:
                        self.irrelevant += 1
                        logger.info(f"❌ Article with ID '{raw_article_id}' is not relevant (score: {relevance_score})")

                    logger.info(f"Total relevant articles: {self.total_relevant}")
                    logger.info(f"Remaining articles to process: {remaining}")

            except RateLimitError as e:
                logger.warning(f"Rate limit exceeded: {e}")
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Error processing article ID {article.get('id', '')}: {e}")

        except Exception as e:
            logger.error(f"Error processing article ID {article.get('id', '')}: {e}")

    async def process_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process articles in optimized batches"""
        try:
            # Get total unanalyzed articles for progress tracking
            total_unanalyzed = self.article_manager.get_unanalyzed_count()
            remaining = total_unanalyzed
            results = []
            
            for i in range(0, len(articles), self.batch_size):
                batch = articles[i:i + self.batch_size]
                
                # Process articles one by one to properly update the remaining count
                batch_results = []
                for article in batch:
                    result = await self.process_article(article, remaining)
                    if result:
                        batch_results.append(result)
                    # Decrement remaining count after each article is processed
                    remaining -= 1
                
                valid_results = [r for r in batch_results if not isinstance(r, Exception)]
                results.extend(valid_results)
                
                # Update progress after each batch
                processed_so_far = total_unanalyzed - remaining
                if hasattr(self, 'progress_callback'):
                    self.progress_callback(processed_so_far, total_unanalyzed)
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing articles: {e}")
            return []

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
            from src.analysis_utils import analyze_relevance_results, print_analysis_results
            
            analysis_results = analyze_relevance_results(
                processor.relevant, 
                processor.irrelevant, 
                processor.max_relevance_score
            )
            logger.info(f"Processing completed. Processed {len(results)} articles.")
            print_analysis_results(analysis_results)
        else:
            logger.error("Processing failed")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        db_manager.close()

