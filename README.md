# Smart News Scraper

A modern GUI application for scraping, analyzing, and managing news articles based on customizable search terms and AI-powered relevance filtering.

## Features

- 📰 **Article Scraping**: Automatically fetch news articles using the NewsAPI
- 🤖 **AI-Powered Analysis**: Evaluate article relevance using OpenAI's API
- 🔍 **Custom Search Terms**: Manage and organize your search terms
- 📊 **Visual Progress Tracking**: Real-time processing status and progress indicators
- 💾 **Persistent Storage**: SQLite database for storing articles and search terms
- 📁 **Import/Export**: Support for importing/exporting search terms and results
- 🎨 **Modern UI**: Clean, intuitive interface with dark theme support

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| Relevance Threshold | Minimum relevance score for articles | 0.7 |
| News API Key | Your NewsAPI authentication key | None |
| OpenAI API Key | Your OpenAI API key for analysis | None |

## Development

This project uses:
- Python 3.8+
- tkinter/ttk for the GUI
- SQLite for data storage
- NewsAPI for article fetching
- OpenAI API for relevance analysis

### Project Structure
```
smart-news-scraper/
├── src/
│   ├── gui.py              # Main GUI application
│   ├── news_scraper.py     # News API integration
│   ├── article_validator.py # Article validation
│   ├── database_manager.py  # SQLite operations
│   └── config.py           # Configuration management
├── tests/                  # Unit tests
└── docs/                   # Documentation
```

## Acknowledgments

- Built with [ttkthemes](https://ttkthemes.readthedocs.io/) for modern UI
- Powered by [OpenAI](https://openai.com/) for article analysis
- News data provided by [NewsAPI](https://newsapi.org/)
