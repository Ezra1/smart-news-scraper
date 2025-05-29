#!/usr/bin/env python3
"""
Build script for Smart News Scraper
Creates an executable and a ZIP installer package
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import zipfile
import json
from datetime import datetime

# Ensure required directories exist
def ensure_directories():
    """Create necessary directories if they don't exist"""
    directories = [
        "batch/input",
        "batch/output",
        "output",
        "dist",
        "build"
    ]
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)

# Create default config file if it doesn't exist
def create_default_config():
    """Create a default config.json file if it doesn't exist"""
    config_path = Path("config.json")
    if not config_path.exists():
        default_config = {
            "NEWS_API_URL": "https://newsapi.org/v2/everything",
            "NEWS_API_DAILY_LIMIT": 100,
            "NEWS_API_REQUESTS_PER_SECOND": 1,
            "OPENAI_REQUESTS_PER_MINUTE": 60,
            "RELEVANCE_THRESHOLD": 0.6,
            "BATCH_SIZE": 100,
            "DATABASE_PATH": "news_articles.db",
            "LOGGING_LEVEL": "INFO",
            "OUTPUT_DIR": "output",
            "CHATGPT_CONTEXT_MESSAGE": {
                "role": "system",
                "content": "You are an AI trained to analyze news articles for relevance. Rate each article's relevance from 0.0 to 1.0."
            }
        }
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)
        print(f"Created default config file at {config_path}")

# Build the executable
def build_executable():
    """Build the executable using PyInstaller"""
    print("Building executable with PyInstaller...")
    result = subprocess.run(
        ["pyinstaller", "--clean", "smart_news_scraper.spec"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("Error building executable:")
        print(result.stderr)
        return False
    
    print("Executable built successfully")
    return True

# Create ZIP installer
def create_zip_installer():
    """Create a ZIP installer package"""
    print("Creating ZIP installer package...")
    
    # Get version from date
    version = datetime.now().strftime("%Y%m%d")
    zip_filename = f"SmartNewsScraper_v{version}.zip"
    
    # Create ZIP file
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add files from dist directory
        dist_dir = Path("dist/SmartNewsScraper")
        if dist_dir.exists() and dist_dir.is_dir():
            for root, _, files in os.walk(dist_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, "dist")
                    zipf.write(file_path, arcname)
        
        # Add README
        if Path("README.md").exists():
            zipf.write("README.md")
        
        # Add search_terms.txt
        if Path("search_terms.txt").exists():
            zipf.write("search_terms.txt")
        
        # Add default config
        if Path("config.json").exists():
            zipf.write("config.json")
    
    print(f"ZIP installer created: {zip_filename}")
    return zip_filename

def main():
    """Main build process"""
    print("Starting build process for Smart News Scraper...")
    
    # Ensure directories exist
    ensure_directories()
    
    # Create default config
    create_default_config()
    
    # Build executable
    if not build_executable():
        print("Build failed")
        return 1
    
    # Create ZIP installer
    zip_file = create_zip_installer()
    
    print(f"\nBuild completed successfully!")
    print(f"Executable: dist/SmartNewsScraper/SmartNewsScraper.exe")
    print(f"ZIP Installer: {zip_file}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())