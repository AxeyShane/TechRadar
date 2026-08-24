"""Config and path resolution for TechRadar."""

from pathlib import Path

import yaml
from dotenv import load_dotenv

# Repo layout: src/techradar/config.py -> repo root is two parents up
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

# Runtime state (db, .env) lives outside the repo, like ApplyPilot's ~/.applypilot
APP_DIR = Path.home() / ".techradar"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "techradar.db"

load_dotenv(APP_DIR / ".env")


def load_sources() -> dict:
    path = CONFIG_DIR / "sources.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_interests() -> dict:
    path = CONFIG_DIR / "interests.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
