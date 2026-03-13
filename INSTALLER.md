# Smart News Scraper - MSI Installer Guide

This document provides instructions for building and using the MSI installer for the Smart News Scraper application.

## Prerequisites

To build the MSI installer, you need:

1. **Python 3.8+** installed and in your PATH
2. **WiX Toolset v3.11** installed
   - Download from: https://wixtoolset.org/releases/
   - Direct download link: https://github.com/wixtoolset/wix3/releases/download/wix3112rtm/wix311.exe
   - Default install location: `C:\Program Files (x86)\WiX Toolset v3.11`
   - **Important**: You must install WiX Toolset before running the build script
3. **PyInstaller** (will be installed automatically if missing)
4. All project dependencies installed (`pip install -r requirements.txt`)

### Installing WiX Toolset

1. Download WiX Toolset v3.11 from https://github.com/wixtoolset/wix3/releases/download/wix3112rtm/wix311.exe
2. Run the installer and follow the installation wizard
3. Accept the default installation location (`C:\Program Files (x86)\WiX Toolset v3.11`)
4. After installation, you may need to restart your computer

## Building the MSI Installer

### Option 1: Using the Batch File (Recommended)

1. Open a Command Prompt in the project directory
2. Run the batch file:
   ```
   build_installer.bat
   ```
3. The MSI installer will be created in the `installer` directory

### Option 2: Using the Python Script Directly

1. Open a Command Prompt in the project directory
  2. Run the Python script:
   ```
   python build_msi.py
   ```
3. The MSI installer will be created in the `installer` directory

### Command-Line Options

- `--skip-build`: Skip building the executable (useful if you've already built it)
  ```
  build_installer.bat --skip-build
  ```
- `--version`: Override the version suffix used in output names
  ```
  python build_msi.py --skip-build --version 1.0.1
  ```

## Installation

1. Download `SmartNewsScraper_v<version>.msi` from:
   - https://github.com/Ezra1/smart-news-scraper/releases/latest
2. Run the MSI installer
3. Follow the installation wizard
4. The application will be installed to `C:\Program Files\Smart News Scraper` by default
5. Shortcuts will be created on the desktop and in the Start Menu

## Uninstallation

1. Go to Control Panel > Programs > Programs and Features
2. Select "Smart News Scraper" and click "Uninstall"
3. Follow the uninstallation wizard

## Troubleshooting

### WiX Toolset Not Found

If you get an error about WiX Toolset not being found:

1. Make sure WiX Toolset v3.11 is installed
2. If installed to a non-default location, update the `WIX_DIR` variable in `build_msi.py`

### PyInstaller Errors

If you encounter errors during the PyInstaller build:

1. Make sure all dependencies are installed: `pip install -r requirements.txt`
2. Check the PyInstaller output for specific errors
3. Try running PyInstaller directly: `pyinstaller --clean smart_news_scraper.spec`

### Installer size is unexpectedly large

Excessively large installers (multiple GB) are usually caused by bundling development artifacts or unused Qt WebEngine components. To reduce the footprint:

1. Ensure you are not building from inside a virtual environment folder and that directories such as `venv/`, `.git/`, `build/`, and `__pycache__/` are excluded from the package inputs.
2. Start from a clean workspace before running PyInstaller:
   - Linux/macOS: `rm -rf build dist`
   - Windows: delete the `build` and `dist` folders in the project root
3. The PyInstaller spec excludes Qt WebEngine modules by default. If you customized the spec, re-run with `--clean` to regenerate a trimmed build: `pyinstaller --clean smart_news_scraper.spec`.
4. Inspect the generated `dist/SmartNewsScraper` folder and remove unnecessary extras (e.g., old log/output dumps) before packaging. The spec intentionally skips bundling `logs/` and `output/` so that leftover run artifacts do not inflate the installer.
5. Heavy ML frameworks (e.g., PyTorch, TensorFlow, NVIDIA CUDA toolkits) are excluded in the spec because they are not used by the app but can silently inflate bundle size if present in your environment. If you re-enable imports or add similar libraries, update the `excludes` list in `smart_news_scraper.spec` accordingly.

### MSI Build Errors

If you encounter errors during the MSI build:

1. Check that WiX Toolset is properly installed
2. Look for specific error messages in the output
3. Make sure you have write permissions to the output directories

## Custom Configuration

To customize the installer:

1. Edit `installer.wxs` to change product information, features, etc.
2. Edit `smart_news_scraper.spec` to change what files are included in the executable
3. Edit `build_msi.py` to change build parameters

## Support

If you encounter any issues with the installer, please open an issue:
https://github.com/Ezra1/smart-news-scraper/issues

## GitHub Release Workflow

This repository includes a GitHub Actions release workflow at
`.github/workflows/release.yml`.

- Create and push a tag like `v1.0.1` to trigger a release build.
- The workflow publishes ZIP and MSI artifacts to GitHub Releases.
- The release is marked as latest so users can always download from:
  https://github.com/Ezra1/smart-news-scraper/releases/latest