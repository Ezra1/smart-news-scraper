import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock, call
import sys
from pathlib import Path
from main import database_transaction, main

# Import the main module using absolute import
sys.path.append(str(Path(__file__).resolve().parent))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@pytest.fixture
def mock_db():
    db = Mock()
    db.get_connection.return_value.__enter__.return_value = Mock()
    db.get_connection.return_value.__exit__.return_value = None
    return db

@pytest.fixture
def mock_config():
    config = Mock()
    config.validate.return_value = True
    return config

@pytest.fixture
def mock_managers():
    search_manager = Mock()
    article_manager = Mock()
    processor = Mock()
    scraper = AsyncMock()
    return search_manager, article_manager, processor, scraper

class TestDatabaseTransaction:
    def test_successful_transaction(self, mock_db):
        with database_transaction(mock_db):
            pass
        
        mock_db.get_connection().__enter__.assert_called_once()
        mock_db.get_connection().__exit__.assert_called_once()
        mock_db.get_connection().__enter__().commit.assert_called_once()

    def test_failed_transaction(self, mock_db):
        with pytest.raises(Exception):
            with database_transaction(mock_db):
                raise Exception("Test error")
        
        mock_db.get_connection().__enter__.assert_called_once()
        mock_db.get_connection().__exit__.assert_called_once()
        mock_db.get_connection().__enter__().rollback.assert_called_once()

@pytest.mark.asyncio
class TestMain:
    @patch('builtins.input')
    @patch('builtins.print')
    async def test_normal_execution(self, mock_print, mock_input, mock_db, mock_config, mock_managers):
        search_manager, article_manager, processor, scraper = mock_managers
        mock_input.side_effect = [
            '',  # database path
            '',  # search terms file
            'n'   # delete old articles
        ]
        
        processor.process_articles.return_value = True
        scraper.fetch_all_articles.return_value = [{'search_term_id': 1, 'content': 'test'}]
        scraper.rate_limited = False

        with patch('main.DatabaseManager', return_value=mock_db), \
             patch('main.ConfigManager', return_value=mock_config), \
             patch('main.SearchTermManager', return_value=search_manager), \
             patch('main.ArticleManager', return_value=article_manager), \
             patch('main.BatchProcessor', return_value=processor), \
             patch('main.NewsArticleScraper', return_value=scraper), \
             patch('main.RelevanceFilter') as mock_filter:

            await main()

            assert mock_input.call_count == 3
            assert mock_db.close.called
            assert search_manager.insert_search_terms_from_txt.called
            assert scraper.fetch_all_articles.called

    @patch('builtins.input')
    @patch('builtins.print')
    async def test_config_validation_failure(self, mock_print, mock_input, mock_config):
        mock_config.validate.return_value = False
        
        with patch('main.ConfigManager', return_value=mock_config):
            await main()
            
            mock_print.assert_any_call("Configuration error: Missing API keys")

    @patch('builtins.input')
    @patch('builtins.print')
    async def test_delete_old_articles(self, mock_print, mock_input, mock_db, mock_config, mock_managers):
        search_manager, article_manager, processor, scraper = mock_managers
        mock_input.side_effect = [
            '',  # database path
            '',  # search terms file
            'y'   # delete old articles
        ]

        with patch('main.DatabaseManager', return_value=mock_db), \
             patch('main.ConfigManager', return_value=mock_config), \
             patch('main.SearchTermManager', return_value=search_manager), \
             patch('main.ArticleManager', return_value=article_manager), \
             patch('main.BatchProcessor', return_value=processor), \
             patch('main.NewsArticleScraper', return_value=scraper):

            await main()

            assert mock_db.execute_query.call_count == 2
            mock_db.execute_query.assert_has_calls([
                call("DELETE FROM raw_articles;"),
                call("DELETE FROM cleaned_articles;")
            ])

    @patch('builtins.input')
    @patch('builtins.print')
    async def test_no_articles_fetched(self, mock_print, mock_input, mock_db, mock_config, mock_managers):
        search_manager, article_manager, processor, scraper = mock_managers
        mock_input.side_effect = [
            '',  # database path
            '',  # search terms file
            'n'   # delete old articles
        ]
        
        scraper.fetch_all_articles.return_value = []

        with patch('main.DatabaseManager', return_value=mock_db), \
             patch('main.ConfigManager', return_value=mock_config), \
             patch('main.SearchTermManager', return_value=search_manager), \
             patch('main.ArticleManager', return_value=article_manager), \
             patch('main.BatchProcessor', return_value=processor), \
             patch('main.NewsArticleScraper', return_value=scraper):

            await main()

            mock_print.assert_any_call("No articles fetched. Proceeding with existing data...")