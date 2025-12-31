# Smart News Scraper

A modern application for scraping, analyzing, and managing news articles based on customizable search terms and AI-powered relevance filtering. The system uses OpenAI's API to evaluate article relevance and provides both command-line and GUI interfaces.

## Features

- 📰 **Article Scraping**: Automatically fetch news articles using The News API
- 🤖 **AI-Powered Analysis**: Evaluate article relevance using OpenAI's API
- 🔍 **Custom Search Terms**: Manage and organize your search terms
- 📊 **Visual Progress Tracking**: Real-time processing status and progress indicators
- 💾 **Persistent Storage**: SQLite database for storing articles and search terms
- 📁 **Import/Export**: Support for importing/exporting search terms and results
- 🎨 **Modern UI**: Clean, intuitive PyQt6-based interface
- 🔒 **Secure Configuration**: Encrypted storage of API keys
- 📱 **Cross-Platform**: Works on Windows, macOS, and Linux with cross-platform machine identification
- 📦 **Standalone Application**: Can be packaged as a standalone executable

## Getting Started

### Prerequisites

- Python 3.8+
- The News API token (get one at [thenewsapi.com](https://www.thenewsapi.com/))
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
   # Copy the template and add your API keys
   cp config/config.template.json config/config.json
   # Then edit config/config.json and enter your keys, e.g.:
   {
     "NEWS_API_KEY": "your_thenewsapi_token_here",
     "OPENAI_API_KEY": "your_openai_api_key_here",
     "RELEVANCE_THRESHOLD": 0.7
   }
   ```

### Usage

#### Command Line Interface

Run the main script:
```bash
python main.py
```

This will:
1. Load search terms from `search_terms.txt` (pharmaceutical security/threat-intel focused)
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
- Search term management (add, remove, import, export)
- Article browsing with filtering options
- Relevance filtering with adjustable threshold
- Configuration settings for API keys
- Real-time progress tracking
- Export functionality (CSV, JSON, TXT)

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| RELEVANCE_THRESHOLD | Minimum relevance score for articles | 0.7 |
| NEWS_API_KEY | Your The News API token | None |
| OPENAI_API_KEY | Your OpenAI API key for analysis | None |
| NEWS_API_URL | The News API endpoint URL | https://api.thenewsapi.com/v1/news/all |
| NEWS_API_REQUESTS_PER_SECOND | Rate limit for The News API | 1 |
| OPENAI_REQUESTS_PER_MINUTE | Rate limit for OpenAI API | 60 |
| BATCH_SIZE | Number of articles to process in parallel | 100 |
| DATABASE_PATH | Path to SQLite database | data/news_articles.db |
| LOGGING_LEVEL | Logging verbosity | INFO |
| CHATGPT_CONTEXT_MESSAGE | System prompt for OpenAI | Custom relevance instructions |

Configuration is stored in `config/config.json` (create this file by copying
`config/config.template.json` and updating your keys). API keys are stored
securely using encryption.

## Architecture

### Core Components

- **DatabaseManager**: Handles SQLite database operations with connection pooling
- **ArticleManager**: Manages article storage and retrieval
- **SearchTermManager**: Handles search term operations
- **NewsArticleScraper**: Fetches articles from The News API with rate limiting
- **ArticleProcessor**: Processes articles using OpenAI for relevance scoring
- **ArticleValidator**: Cleans and validates article content
- **PipelineManager**: Orchestrates the entire processing workflow
- **RelevanceFilter**: Filters articles based on relevance scores
- **ConfigManager**: Manages configuration with secure API key storage
- **RateLimiter**: Handles API rate limiting for external services

### Data Flow

1. **Search Terms** → Load from file or database
2. **PipelineManager** → Coordinates the processing workflow
3. **NewsArticleScraper** → Fetch articles from The News API
4. **ArticleValidator** → Clean and validate article content
5. **ArticleManager** → Store raw articles in database
6. **ArticleProcessor** → Process articles with OpenAI
7. **RelevanceFilter** → Filter based on relevance scores
8. **DatabaseManager** → Store cleaned articles
9. **Output** → Export cleaned articles to file

## Project Structure

```
smart-news-scraper/
├── src/
│   ├── analysis_base.py         # Base class for article analysis
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
│   ├── news_scraper.py          # The News API integration
│   ├── openai_relevance_processing.py # OpenAI processing
│   ├── pipeline_manager.py      # Processing pipeline
│   ├── qt_gui.py                # PyQt6 GUI implementation
│   └── utils/
│       └── rate_limiter.py      # API rate limiting
├── tests/                       # Unit tests
├── batch/                       # Batch processing directories
│   ├── input/                   # Input files for batch processing
│   └── output/                  # Output files from batch processing
├── output/                      # Output files directory
├── data/                        # Data storage directory
│   └── logs/                    # Application logs
├── main.py                      # CLI entry point
├── gui_main.py                  # GUI entry point
├── build_installer.py           # Packaging script
├── smart_news_scraper.spec      # PyInstaller specification
├── migrate_db.py                # Database migration utility
├── search_terms.txt             # Default search terms
├── config/
│   └── config.template.json     # Copy to config.json and add your keys
└── requirements.txt             # Dependencies
```

## Additional Files

- `pharmaceutical_search_terms.txt` - Example OSINT keywords focused on pharmaceutical security
- `ai_context_prompt.txt` - Default system prompt used for relevance analysis
- `CHANGELOG.md` - Project release notes

## Development

### Running Tests

```bash
python -m pytest tests/
```

Individual tests can be run directly:

```bash
python -m pytest tests/test_openai_api.py
```

### Building a Standalone Executable

The project includes PyInstaller configuration for creating standalone executables.
**Important**: You must run the build on Windows (or inside a Windows VM) because
PyInstaller cannot cross-compile Windows binaries from Linux.
The bundled application runs the GUI entry point defined in `gui_main.py`:

```bash
# Build the executable
python build_installer.py
```

This will:
1. Create necessary directories
2. Generate a default config file if needed
3. Build the executable using PyInstaller
4. Package everything into a ZIP installer

The resulting executable will be in `dist/SmartNewsScraper/`.
Double-click `SmartNewsScraper.exe` to launch the graphical interface.

### Distribution Contents

The `dist/SmartNewsScraper` folder includes the executable along with an
`_internal` directory that stores Python runtime files like
`base_library.zip`. This file is required by the application and should
remain in `_internal`.

Documentation files are copied to the top level of the distribution so
they are easy to find:

- `README.md`
- `requirements.txt`
- `setup.py`
- `CHANGELOG.md`
- `pharmaceutical_search_terms.txt`
- `ai_context_prompt.txt`

### Adding New Features

1. **New Search Source**: Extend the `NewsArticleScraper` class
2. **Custom Relevance Logic**: Modify the `ArticleProcessor` class
3. **New Export Format**: Add to the `extract_cleaned_articles.py` file
4. **UI Enhancements**: Modify the `qt_gui.py` file

## Troubleshooting

- **API Rate Limits**: Adjust the rate limiting settings in `config/config.json`
- **Database Errors**: Check file permissions for the SQLite database
- **OpenAI Errors**: Verify your API key and check OpenAI service status
- **GUI Issues**: Ensure PyQt6 is properly installed
- **Packaging Errors**: Check the PyInstaller spec file and dependencies

## System Requirements

- **Operating System**: Windows 10+, macOS 10.14+, or Linux
- **Memory**: 4GB RAM minimum, 8GB recommended
- **Disk Space**: 500MB for installation, plus space for article storage
- **Internet Connection**: Required for API access

## Acknowledgments

- Powered by [OpenAI](https://openai.com/) for article analysis
- News data provided by [The News API](https://www.thenewsapi.com/)
- GUI built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- SQLite for efficient data storage
- Python's asyncio for concurrent processing
- PyInstaller for application packaging
