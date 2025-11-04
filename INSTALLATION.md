# Smart News Scraper - Installation Guide

This document provides instructions for installing and running the Smart News Scraper application.

## Installation Options

### Option 1: Using the ZIP Installer (Recommended)

1. Download the ZIP installer (`SmartNewsScraper_v[DATE].zip`)
2. Extract the ZIP file to a location of your choice
3. Run `SmartNewsScraper.exe` from the extracted folder to open the GUI

### Option 2: Using the Standalone Executable

1. Download the standalone executable (`SmartNewsScraper.exe`)
2. Place it in a folder of your choice
3. Run the executable to open the GUI

## First-Time Setup

When you run the application for the first time:

1. You'll need to configure your API keys in the Configuration tab:
   - The News API token (from thenewsapi.com)
   - OpenAI API Key (from platform.openai.com)

2. Add search terms in the Search Terms tab:
   - Enter terms related to pharmaceutical security and supply chain integrity
   - You can import terms from a text file (one term per line)

3. Adjust relevance threshold in the Processing tab:
   - Higher values (closer to 1.0) will filter for more relevant articles
   - Lower values (closer to 0.0) will include more articles

## System Requirements

- Windows 10 or later
- 4GB RAM minimum (8GB recommended)
- 500MB free disk space
- Internet connection

## Troubleshooting

### Common Issues

1. **API Key Errors**:
   - Ensure your API keys are entered correctly
   - Check that your API keys are active and have sufficient quota

2. **Database Errors**:
   - The application creates a SQLite database in the same folder
   - Ensure you have write permissions to the folder

3. **Network Issues**:
   - Check your internet connection
   - If you're behind a proxy, configure your system proxy settings

### Getting Help

If you encounter any issues not covered here, please:
1. Check the README.md file for additional information
2. Contact support at support@example.com

## Uninstallation

To uninstall the application:
1. Delete the application folder
2. Optionally, delete the database file (`news_articles.db`) if you don't need the data