# Smart News Scraper

A modern GUI application for scraping, analyzing, and managing news articles based on customizable search terms and AI-powered relevance filtering.

![Smart News Scraper Screenshot](docs/images/app_screenshot.png)

## Features

- 📰 **Article Scraping**: Automatically fetch news articles using the NewsAPI
- 🤖 **AI-Powered Analysis**: Evaluate article relevance using OpenAI's API
- 🔍 **Custom Search Terms**: Manage and organize your search terms
- 📊 **Visual Progress Tracking**: Real-time processing status and progress indicators
- 💾 **Persistent Storage**: SQLite database for storing articles and search terms
- 📁 **Import/Export**: Support for importing/exporting search terms and results
- 🎨 **Modern UI**: Clean, intuitive interface with dark theme support

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/smart-news-scraper.git
   cd smart-news-scraper
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up API keys**:
   Create a `.env` file in the project root:
   ```env
   NEWS_API_KEY=your_news_api_key
   OPENAI_API_KEY=your_openai_api_key
   ```

## Usage

1. **Launch the application**:
   ```bash
   python -m src.gui
   ```

2. **Configure the Application**:
   - Go to the "Configuration" tab
   - Enter your API keys
   - Adjust the relevance threshold

3. **Manage Search Terms**:
   - Use the "Search Terms" tab
   - Add/remove search terms
   - Import terms from a file
   - Export your term list

4. **Process Articles**:
   - Navigate to the "Processing" tab
   - Choose between full processing or step-by-step:
     - Fetch articles
     - Clean article data
     - Analyze relevance
   - Monitor progress in real-time

5. **View Results**:
   - Check the "Results" tab
   - Filter articles by relevance
   - Search through results
   - Export findings for further analysis

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

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [ttkthemes](https://ttkthemes.readthedocs.io/) for modern UI
- Powered by [OpenAI](https://openai.com/) for article analysis
- News data provided by [NewsAPI](https://newsapi.org/)
