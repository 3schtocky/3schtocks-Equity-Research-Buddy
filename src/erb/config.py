"""Paths and settings shared across modules."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
COVERAGE_DIR = ROOT / "coverage"
GUIDES_DIR = ROOT / "guides"
ASSETS_DIR = ROOT / "assets"

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT", "Conscious Investments stott@consciousinvestments.org"
)


def coverage_dir(ticker: str) -> Path:
    path = COVERAGE_DIR / ticker.upper()
    path.mkdir(parents=True, exist_ok=True)
    return path
