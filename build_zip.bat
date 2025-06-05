@echo off
echo Creating ZIP installer for Smart News Scraper
echo ==========================================

REM Check if executable exists
if not exist "dist\SmartNewsScraper\SmartNewsScraper.exe" (
    echo Error: Executable not found. Please run build_exe.bat first.
    exit /b 1
)

REM Create installer directory if it doesn't exist
if not exist "installer" mkdir installer

REM Get current date for version
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (
    set mm=%%a
    set dd=%%b
    set yy=%%c
)

set VERSION=%yy%%mm%%dd%
set ZIP_FILE=installer\SmartNewsScraper_v%VERSION%.zip

REM Create ZIP file
echo Creating ZIP file: %ZIP_FILE%
powershell -Command "Compress-Archive -Path 'dist\SmartNewsScraper\*' -DestinationPath '%ZIP_FILE%' -Force"

REM Add additional files
powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = [System.IO.Compression.ZipFile]::Open('%ZIP_FILE%', 'Update'); [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, 'README.md', 'README.md'); $zip.Dispose()"

if exist "search_terms.txt" (
    powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = [System.IO.Compression.ZipFile]::Open('%ZIP_FILE%', 'Update'); [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, 'search_terms.txt', 'search_terms.txt'); $zip.Dispose()"
)

if exist "config.json" (
    powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip = [System.IO.Compression.ZipFile]::Open('%ZIP_FILE%', 'Update'); [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, 'config.json', 'config.json'); $zip.Dispose()"
)

echo ZIP installer created successfully: %ZIP_FILE%