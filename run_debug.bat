@echo off
:: Debug launcher for SmartNewsScraper Windows build.
:: Purpose:
::   Run SmartNewsScraper.exe and capture stdout/stderr to output.txt for inspection.
::
:: Usage:
::   run_debug.bat
::
:: Requirements:
::   - SmartNewsScraper.exe built (PyInstaller or MSI install)
::   - Write access to the current directory for output.txt

echo Starting SmartNewsScraper...
SmartNewsScraper.exe > output.txt 2>&1
echo Program finished. Check output.txt for results.
pause