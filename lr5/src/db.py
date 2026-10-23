"""Shared PostgreSQL connection settings for LR5 scripts."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DELIVERIES_FILE = DATA_DIR / "deliveries.jsonl"


def connection_parameters(database: str | None = None) -> dict[str, object]:
    """Return connection parameters compatible with the LR1 local setup."""

    return {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "55432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", "postgres"),
        "dbname": database or os.getenv("PGDATABASE", "supply_lab"),
    }
