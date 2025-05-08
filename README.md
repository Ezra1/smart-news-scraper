# Smart News Scraper

A modern application for scraping, analyzing, and managing news articles based on customizable search terms and AI-powered relevance filtering. The system uses OpenAI's API to evaluate article relevance and provides both command-line and GUI interfaces.

## Features

- 📰 **Article Scraping**: Automatically fetch news articles using the NewsAPI
- 🤖 **AI-Powered Analysis**: Evaluate article relevance using OpenAI's API
- 🔍 **Custom Search Terms**: Manage and organize your search terms
- 📊 **Visual Progress Tracking**: Real-time processing status and progress indicators
- 💾 **Persistent Storage**: SQLite database for storing articles and search terms
- 📁 **Import/Export**: Support for importing/exporting search terms and results
- 🎨 **Modern UI**: Clean, intuitive interface with dark theme support
- 🔒 **Secure Configuration**: Encrypted storage of API keys

## Getting Started

### Prerequisites

- Python 3.8+
- NewsAPI key (get one at [newsapi.org](https://newsapi.org/))
- OpenAI API key (get one at [openai.com](https://platform.openai.com/))

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/smart-news-scraper.git
   cd smart-news-scraper
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up configuration:
   ```bash
   python -m src.config
   ```
   Follow the prompts to enter your API keys.

### Usage

#### Command Line Interface

Run the main script:
```bash
python main.py
```

This will:
1. Load search terms from `search_terms.txt`
2. Fetch articles based on those terms
3. Process articles for relevance using OpenAI
4. Save relevant articles to the database
5. Export cleaned articles to your desktop

#### GUI Interface

Launch the GUI application:
```bash
python gui_main.py
```

The GUI provides:
- Search term management
- Article browsing
- Relevance filtering
- Configuration settings

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| RELEVANCE_THRESHOLD | Minimum relevance score for articles | 0.6 |
| NEWS_API_KEY | Your NewsAPI authentication key | None |
| OPENAI_API_KEY | Your OpenAI API key for analysis | None |
| NEWS_API_REQUESTS_PER_SECOND | Rate limit for NewsAPI | 1 |
| OPENAI_REQUESTS_PER_MINUTE | Rate limit for OpenAI API | 60 |
| BATCH_SIZE | Number of articles to process in parallel | 100 |

Configuration is stored in `config.json` in the project root. API keys are stored securely using encryption.

## Architecture

### Core Components

- **DatabaseManager**: Handles SQLite database operations with connection pooling
- **ArticleManager**: Manages article storage and retrieval
- **NewsArticleScraper**: Fetches articles from NewsAPI
- **ArticleProcessor**: Processes articles using OpenAI for relevance scoring
- **RelevanceFilter**: Filters articles based on relevance scores
- **ConfigManager**: Manages configuration with secure API key storage

### Data Flow

1. **Search Terms** → Load from file or database
2. **NewsArticleScraper** → Fetch articles from NewsAPI
3. **ArticleManager** → Store raw articles in database
4. **ArticleProcessor** → Process articles with OpenAI
5. **RelevanceFilter** → Filter based on relevance scores
6. **DatabaseManager** → Store cleaned articles
7. **Output** → Export cleaned articles to file

## Project Structure

```
smart-news-scraper/
├── src/
│   ├── analysis_utils.py        # Shared analysis utilities
│   ├── api_validator.py         # API validation
│   ├── article_deduplicator.py  # Article deduplication
│   ├── article_validator.py     # Article validation
│   ├── config.py                # Configuration management
│   ├── database_manager.py      # SQLite operations
│   ├── extract_cleaned_articles.py # Export functionality
│   ├── insert_processed_articles.py # Relevance filtering
│   ├── insert_search_terms.py   # Search term management
│   ├── logger_config.py         # Logging configuration
│   ├── news_scraper.py          # News API integration
│   ├── openai_client.py         # OpenAI client
│   ├── openai_relevance_processing.py # OpenAI processing
│   ├── pipeline_manager.py      # Processing pipeline
│   ├── qt_gui.py                # GUI implementation
│   └── rate_limiter.py          # API rate limiting
├── tests/                       # Unit tests
├── config/                      # Configuration files
├── data/                        # Data storage
├── output/                      # Output files
├── main.py                      # CLI entry point
├── gui_main.py                  # GUI entry point
└── requirements.txt             # Dependencies
```

## Development

### Running Tests

```bash
python -m pytest tests/
```

Individual tests can be run directly:

```bash
python tests/test_openai_api.py
```

### Adding New Features

1. **New Search Source**: Extend the `NewsArticleScraper` class
2. **Custom Relevance Logic**: Modify the `ArticleProcessor` class
3. **New Export Format**: Add to the `extract_cleaned_articles.py` file

## Troubleshooting

- **API Rate Limits**: Adjust the rate limiting settings in config.json
- **Database Errors**: Check file permissions for the SQLite database
- **OpenAI Errors**: Verify your API key and check OpenAI service status

## Acknowledgments

- Powered by [OpenAI](https://openai.com/) for article analysis
- News data provided by [NewsAPI](https://newsapi.org/)
- SQLite for efficient data storage
- Python's asyncio for concurrent processing
