#!/usr/bin/env python3
"""
Build script for Smart News Scraper MSI Installer
This script:
1. Builds the executable using PyInstaller
2. Creates an MSI installer using WiX Toolset
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import json
from datetime import datetime
import tempfile
import argparse

# Define paths
WIX_DIR = r"C:\Program Files (x86)\WiX Toolset v3.11\bin"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist", "SmartNewsScraper")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "installer")

# Ensure required directories exist
def ensure_directories():
    """Create necessary directories if they don't exist"""
    directories = [
        "batch/input",
        "batch/output",
        "output",
        "dist",
        "build",
        "installer"
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

# Check if WiX Toolset is installed
def check_wix_toolset():
    """Check if WiX Toolset is installed"""
    if not os.path.exists(WIX_DIR):
        print("WiX Toolset not found at:", WIX_DIR)
        print("Please install WiX Toolset v3.11 or update the WIX_DIR path in this script.")
        return False
    return True

# Generate WiX component file using heat.exe
def generate_wix_components():
    """Generate WiX component file for all files in dist folder"""
    print("Generating WiX components...")
    
    # Path to heat.exe
    heat_path = os.path.join(WIX_DIR, "heat.exe")
    
    # Output file
    components_file = os.path.join(PROJECT_ROOT, "components.wxs")
    
    # Run heat.exe to harvest files
    cmd = [
        heat_path,
        "dir",
        DIST_DIR,
        "-cg", "DistributionFiles",
        "-dr", "INSTALLFOLDER",
        "-sreg",  # Suppress registry harvesting
        "-srd",   # Suppress harvesting the root directory as an element
        "-scom",  # Suppress COM elements
        "-sfrag", # Suppress fragments
        "-gg",    # Generate GUIDs
        "-g1",    # Generate component GUIDs without curly braces
        "-ke",    # Keep empty directories
        "-var", "var.SourceDir",
        "-out", components_file
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Error generating WiX components:")
        print(result.stderr)
        return False
    
    print(f"WiX components generated: {components_file}")
    return components_file

# Compile WiX source files
def compile_wix_sources(components_file):
    """Compile WiX source files to object files"""
    print("Compiling WiX source files...")
    
    # Paths to candle.exe
    candle_path = os.path.join(WIX_DIR, "candle.exe")
    
    # Compile installer.wxs
    installer_cmd = [
        candle_path,
        "-dSourceDir=" + DIST_DIR,
        "installer.wxs",
        "-out", os.path.join(BUILD_DIR, "installer.wixobj")
    ]
    
    result1 = subprocess.run(installer_cmd, capture_output=True, text=True)
    
    if result1.returncode != 0:
        print("Error compiling installer.wxs:")
        print(result1.stderr)
        return False
    
    # Compile components.wxs
    components_cmd = [
        candle_path,
        "-dSourceDir=" + DIST_DIR,
        components_file,
        "-out", os.path.join(BUILD_DIR, "components.wixobj")
    ]
    
    result2 = subprocess.run(components_cmd, capture_output=True, text=True)
    
    if result2.returncode != 0:
        print("Error compiling components.wxs:")
        print(result2.stderr)
        return False
    
    print("WiX source files compiled successfully")
    return True

# Link WiX object files to create MSI
def link_wix_objects():
    """Link WiX object files to create MSI"""
    print("Linking WiX object files...")
    
    # Path to light.exe
    light_path = os.path.join(WIX_DIR, "light.exe")
    
    # Get version from date
    version = datetime.now().strftime("%Y%m%d")
    msi_filename = f"SmartNewsScraper_v{version}.msi"
    msi_path = os.path.join(OUTPUT_DIR, msi_filename)
    
    # Link object files
    cmd = [
        light_path,
        "-ext", "WixUIExtension",
        "-cultures:en-us",
        "-out", msi_path,
        os.path.join(BUILD_DIR, "installer.wixobj"),
        os.path.join(BUILD_DIR, "components.wixobj")
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Error linking WiX object files:")
        print(result.stderr)
        return False
    
    print(f"MSI installer created: {msi_path}")
    return msi_path

def main():
    """Main build process"""
    parser = argparse.ArgumentParser(description="Build MSI installer for Smart News Scraper")
    parser.add_argument("--skip-build", action="store_true", help="Skip building the executable")
    args = parser.parse_args()
    
    print("Starting build process for Smart News Scraper MSI installer...")
    
    # Ensure directories exist
    ensure_directories()
    
    # Create default config
    create_default_config()
    
    # Check if WiX Toolset is installed
    if not check_wix_toolset():
        print("WiX Toolset is required to build the MSI installer.")
        print("Please install WiX Toolset v3.11 from: https://wixtoolset.org/releases/")
        return 1
    
    # Build executable (unless skipped)
    if not args.skip_build:
        if not build_executable():
            print("Build failed")
            return 1
    else:
        print("Skipping executable build as requested")
        if not os.path.exists(os.path.join(DIST_DIR, "SmartNewsScraper.exe")):
            print("Error: Executable not found. Please build it first or remove --skip-build flag.")
            return 1
    
    # Generate WiX components
    components_file = generate_wix_components()
    if not components_file:
        return 1
    
    # Compile WiX sources
    if not compile_wix_sources(components_file):
        return 1
    
    # Link WiX objects
    msi_path = link_wix_objects()
    if not msi_path:
        return 1
    
    print(f"\nBuild completed successfully!")
    print(f"Executable: {DIST_DIR}/SmartNewsScraper.exe")
    print(f"MSI Installer: {msi_path}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())