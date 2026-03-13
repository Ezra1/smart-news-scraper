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
import os
import shutil
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

    candle, light = resolve_wix_tools()

    run([candle, str(wxs), "-o", str(wixobj)])
    run([light, str(wixobj), "-o", str(msi)])
    print(f"Created {msi}")


def resolve_wix_tools() -> tuple[str, str]:
    """Resolve candle.exe and light.exe from PATH or common WiX install folders."""
    candle_on_path = shutil.which("candle.exe") or shutil.which("candle")
    light_on_path = shutil.which("light.exe") or shutil.which("light")
    if candle_on_path and light_on_path:
        return candle_on_path, light_on_path

    candidate_bins = [Path(WIX_DIR)]
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    program_files = os.environ.get("ProgramFiles")
    common_roots = [program_files_x86, program_files]
    wix_versions = ["v3.11", "v3.14", "v3.15", "v3.16", "v3.17"]
    for root in common_roots:
        if not root:
            continue
        for version in wix_versions:
            candidate_bins.append(Path(root) / f"WiX Toolset {version}" / "bin")
            candidate_bins.append(Path(root) / f"Wix Toolset {version}" / "bin")

    for bin_dir in candidate_bins:
        candle = bin_dir / "candle.exe"
        light = bin_dir / "light.exe"
        if candle.exists() and light.exists():
            return str(candle), str(light)

    raise FileNotFoundError(
        "Could not locate WiX tools (candle.exe/light.exe). "
        "Install WiX and ensure tools are on PATH, or update WIX_DIR in build_msi.py."
    )


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
