"""
Seed source databases with the dirty demo datasets.

Tables mimic a legacy system: every column is text, headers keep their original
messy names, and blanks are stored as empty strings. Each SQL table is
(re)created and filled inside one transaction.

Usage:
    python data/seed_postgres.py                          # PostgreSQL only (default)
    python data/seed_postgres.py postgresql mysql mongodb duckdb sqlite
    PG_TABLE=dirty_orders python data/seed_postgres.py
"""

import os
import sys

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from etl.endpoints import Endpoint, default_config  # noqa: E402

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

DEMO_DATASETS = {
    "dirty_employees": "dirty_employees.csv",
    "dirty_orders": "dirty_orders.csv",
}


def seed_endpoint(endpoint, tables=None):
    """Seed demo tables into any source endpoint. Returns {table: rows}."""
    seeded = {}
    for table, fname in DEMO_DATASETS.items():
        if tables and table not in tables:
            continue
        df = pd.read_csv(os.path.join(DATA_DIR, fname), dtype=str, keep_default_na=False)
        seeded[table] = endpoint.seed_raw(table, df)
        print(f"[OK] Seeded {endpoint.label} '{table}' with {seeded[table]} rows")
    return seeded


def seed_postgres(pg_config=None, tables=None):
    """Backwards-compatible helper: seed PostgreSQL."""
    cfg = {**default_config("postgresql"), **(pg_config or {})}
    return seed_endpoint(Endpoint("postgresql", cfg), tables)


if __name__ == "__main__":
    kinds = sys.argv[1:] or ["postgresql"]
    only = os.environ.get("PG_TABLE")
    for kind in kinds:
        seed_endpoint(Endpoint(kind, default_config(kind, "source")), [only] if only else None)
