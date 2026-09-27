"""Repository paths; works for an editable install as well as a source checkout."""

from pathlib import Path

# src/gridcast/config.py -> repo root is two levels up from this file
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Native step of each market's demand series, in minutes.
CADENCE_MINUTES = {"GB": 30, "IE": 15, "AU": 5, "FR": 15, "DE": 15, "BE": 15, "DK": 60}

MARKETS = tuple(CADENCE_MINUTES)
