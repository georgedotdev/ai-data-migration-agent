"""
Seed the PostgreSQL source database with the dirty demo datasets.

The tables mimic a legacy system: every column is TEXT, headers keep their
original messy names, and blanks are stored as empty strings. Each table is
(re)created and filled inside one transaction.

Usage:
    python data/seed_postgres.py            # seeds every demo table
    PG_TABLE=dirty_orders python data/seed_postgres.py
"""

import os
import sys

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from connectors.postgres_connector import PostgreSQLConnector  # noqa: E402
from etl.sql_schema import safe_ident  # noqa: E402

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

DEMO_DATASETS = {
    "dirty_employees": "dirty_employees.csv",
    "dirty_orders": "dirty_orders.csv",
}


def _pg_col(name):
    return '"' + str(name).replace('"', '""') + '"'


def seed_table(engine, table, csv_path):
    safe_ident(table)
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    cols = ", ".join(f"{_pg_col(c)} TEXT" for c in df.columns)
    placeholders = ", ".join(f":c{i}" for i in range(len(df.columns)))
    insert = text(f'INSERT INTO "{table}" VALUES ({placeholders})')
    rows = [{f"c{i}": v for i, v in enumerate(r)} for r in df.itertuples(index=False, name=None)]
    with engine.begin() as conn:   # one transaction: all rows or nothing
        conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
        conn.execute(text(f'CREATE TABLE "{table}" ({cols})'))
        conn.execute(insert, rows)
    return len(df)


def seed_postgres(pg_config=None, tables=None):
    """Seed demo tables. Returns {table: rows} and raises on failure."""
    connector = PostgreSQLConnector(**(pg_config or {}))
    seeded = {}
    for table, fname in DEMO_DATASETS.items():
        if tables and table not in tables:
            continue
        seeded[table] = seed_table(connector.engine, table, os.path.join(DATA_DIR, fname))
        print(f"[OK] Seeded '{table}' with {seeded[table]} rows")
    return seeded


if __name__ == "__main__":
    only = os.environ.get("PG_TABLE")
    seed_postgres(tables=[only] if only else None)
