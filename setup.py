import sys
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need fine tuning.
build_exe_options = {
    "packages": [
        "os", "sys", "logging", "json", "asyncio", "aiohttp", "openai",
        "pandas", "numpy", "scipy", "sklearn", "bs4", "requests", "urllib3",
        "sqlite3", "datetime", "re", "traceback", "PyQt6", "PyQt6.QtCore",
        "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtNetwork"
    ],
    "excludes": [],
    "include_files": [
        "config/",
        "data/",
        "logs/",
        "output/",
        "src/",
        "requirements.txt",
        "README.md",
        "INSTALLATION.md",
        "INSTALLER.md",
        "LICENSE",
        "CHANGELOG.md",
        "pharmaceutical_search_terms.txt",
        "ai_context_prompt.txt"
    ],
    "include_msvcr": True,
    "zip_include_packages": "*",
    "zip_exclude_packages": "",
    "build_exe": "build/SmartNewsScraper",
    "optimize": 2,
}

# GUI applications require a different base on Windows
base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(
    name="SmartNewsScraper",
    version="1.0",
    description="Smart News Scraper Application",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "gui_main.py",
            base=base,
            target_name="SmartNewsScraper.exe",
            icon="config/icon.ico",
            copyright="Copyright © 2024",
            shortcut_name="Smart News Scraper",
            shortcut_dir="DesktopFolder"
        )
    ]
) 
