@echo off
echo Building Smart News Scraper Executable
echo =====================================

REM Check if Python is installed
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

REM Check if PyInstaller is installed
python -c "import PyInstaller" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Build the executable
echo Building executable with PyInstaller...
pyinstaller --clean smart_news_scraper.spec

if %ERRORLEVEL% neq 0 (
    echo Build failed with error code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo Build completed successfully!
echo You can find the executable in the 'dist\SmartNewsScraper' directory.
echo To create an MSI installer, install WiX Toolset and run build_installer.bat