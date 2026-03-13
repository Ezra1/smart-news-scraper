#!/usr/bin/env python3
"""Build an MSI installer using the WiX Toolset.

Purpose:
    Produce a Windows MSI installer from the PyInstaller build.

Usage:
    python build_msi.py [--skip-build] [--version VERSION]

Requirements:
    - Windows with WiX Toolset v3.11 installed at WIX_DIR
    - pyinstaller available on PATH
    - smart_news_scraper.spec present in repo root

Examples:
    python build_msi.py           # build executable then MSI
    python build_msi.py --skip-build  # reuse existing PyInstaller output
"""
import argparse
import datetime
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
WIX_DIR = r"C:\\Program Files (x86)\\WiX Toolset v3.11\\bin"


def run(cmd):
    if isinstance(cmd, list):
        subprocess.check_call(cmd)
    else:
        subprocess.check_call(cmd, shell=True)


def build_executable():
    run(["pyinstaller", "--clean", "smart_news_scraper.spec"])


def build_msi(version: str):
    installer_dir = PROJECT_ROOT / "installer"
    installer_dir.mkdir(exist_ok=True)
    wixobj = installer_dir / "installer.wixobj"
    wxs = PROJECT_ROOT / "installer.wxs"
    msi = installer_dir / f"SmartNewsScraper_v{version}.msi"

    candle = f"{WIX_DIR}\\candle.exe"
    light = f"{WIX_DIR}\\light.exe"

    run([candle, str(wxs), "-o", str(wixobj)])
    run([light, str(wixobj), "-o", str(msi)])
    print(f"Created {msi}")


def resolve_version(version_arg: str | None) -> str:
    if version_arg:
        return version_arg
    return datetime.datetime.now().strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(description="Build MSI installer")
    parser.add_argument("--skip-build", action="store_true", help="Skip building the executable")
    parser.add_argument(
        "--version",
        help="Override installer version suffix (default: current date YYYYMMDD)",
    )
    args = parser.parse_args()

    version = resolve_version(args.version)
    if not args.skip_build:
        build_executable()
    build_msi(version)


if __name__ == "__main__":
    main()
