#!/usr/bin/env python3
"""Build a standalone ZIP installer using PyInstaller."""
import shutil
import subprocess
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def ensure_directories() -> None:
    DIST_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)


def ensure_config() -> None:
    template = PROJECT_ROOT / "config" / "config.template.json"
    target = PROJECT_ROOT / "config" / "config.json"
    if not target.exists() and template.exists():
        shutil.copy(template, target)
        print(f"Created default config at {target}")


def build_executable() -> None:
    output_dir = DIST_DIR / "SmartNewsScraper"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    cmd = ["pyinstaller", "--clean", "-y", "smart_news_scraper.spec"]
    subprocess.check_call(cmd)


def move_docs_to_root() -> None:
    """Ensure documentation files reside in the distribution root."""
    output_dir = DIST_DIR / "SmartNewsScraper"
    internal = output_dir / "_internal"
    if not internal.exists():
        return
    docs = [
        "README.md",
        "requirements.txt",
        "setup.py",
        "CHANGELOG.md",
        "pharmaceutical_search_terms.txt",
        "ai_context_prompt.txt",
    ]
    for doc in docs:
        src = internal / doc
        dest = output_dir / doc
        if src.exists():
            shutil.copy(src, dest)


def package_zip() -> None:
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    src = DIST_DIR / "SmartNewsScraper"
    archive_name = PROJECT_ROOT / f"SmartNewsScraper_v{date_str}"
    shutil.make_archive(archive_name.as_posix(), "zip", src)
    print(f"Created {archive_name.with_suffix('.zip')}")


def main() -> None:
    ensure_directories()
    ensure_config()
    build_executable()
    move_docs_to_root()
    package_zip()


if __name__ == "__main__":
    main()

