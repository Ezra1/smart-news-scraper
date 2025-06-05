@echo off
echo Building Smart News Scraper MSI Installer
echo ========================================

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
    if %ERRORLEVEL% neq 0 (
        echo Error: Failed to install PyInstaller
        exit /b 1
    )
)

REM Check if WiX Toolset is installed
if not exist "C:\Program Files (x86)\WiX Toolset v3.11\bin\candle.exe" (
    echo Warning: WiX Toolset v3.11 not found at the expected location.
    echo Please install WiX Toolset v3.11 from: https://wixtoolset.org/releases/
    echo After installation, you may need to restart this script.
    
    choice /C YN /M "Do you want to continue anyway?"
    if %ERRORLEVEL% neq 1 (
        echo Build canceled by user.
        exit /b 1
    )
)

REM Run the build script
python build_msi.py %*

if %ERRORLEVEL% neq 0 (
    echo Build failed with error code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo Build completed successfully!
echo You can find the MSI installer in the 'installer' directory.