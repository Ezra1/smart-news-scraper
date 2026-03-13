#!/usr/bin/env python3
"""Build a standalone ZIP installer using PyInstaller.

Purpose:
    Create a distributable ZIP (PyInstaller one-folder build).

Usage:
    python build_installer.py [--version VERSION]

Requirements:
    - Python environment with pyinstaller installed
    - smart_news_scraper.spec present in repo root
    - Access to config/config.template.json to seed config.json if missing

Outputs:
    - dist/SmartNewsScraper/... with bundled app
    - SmartNewsScraper_v<version>.zip archive in project root
"""
import argparse
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


def resolve_version(version_arg: str | None) -> str:
    if version_arg:
        return version_arg
    return datetime.datetime.now().strftime("%Y%m%d")


def package_zip(version: str) -> None:
    src = DIST_DIR / "SmartNewsScraper"
    archive_name = PROJECT_ROOT / f"SmartNewsScraper_v{version}"
    shutil.make_archive(archive_name.as_posix(), "zip", src)
    print(f"Created {archive_name.with_suffix('.zip')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ZIP installer")
    parser.add_argument(
        "--version",
        help="Override archive version (default: current date YYYYMMDD)",
    )
    args = parser.parse_args()
    version = resolve_version(args.version)
    ensure_directories()
    ensure_config()
    build_executable()
    move_docs_to_root()
    package_zip(version)


if __name__ == "__main__":
    main()

