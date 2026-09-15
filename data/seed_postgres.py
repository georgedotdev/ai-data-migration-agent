"""
Seed Sample Data into PostgreSQL Source Database

Reads data/messy_ecommerce_sales_data.csv and populates
the PostgreSQL source table (default: 'enterprise').

Usage:
    python data/seed_postgres.py
"""

import os
import sys
import pandas as pd
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from connectors.postgres_connector import PostgreSQLConnector


def seed_postgres(table_name=None, csv_filename=None):
    datasets = [
        ("enterprise", "messy_ecommerce_sales_data.csv"),
        ("dirty_employees", "ultra_dirty_employees.csv")
    ]

    if table_name and csv_filename:
        datasets = [(table_name, csv_filename)]
    elif table_name:
        datasets = [(table_name, "messy_ecommerce_sales_data.csv" if table_name == "enterprise" else "ultra_dirty_employees.csv")]

    success = True
    for tbl, csv_f in datasets:
        csv_path = os.path.join(os.path.dirname(__file__), csv_f)
        if not os.path.exists(csv_path):
            print(f"[ERROR] Sample CSV not found at {csv_path}")
            success = False
            continue

        print(f"Reading sample data from {csv_path}...")
        df = pd.read_csv(csv_path)
        print(f"Loaded {len(df)} rows, {len(df.columns)} columns.")

        print(f"Connecting to PostgreSQL and writing to table '{tbl}'...")
        try:
            connector = PostgreSQLConnector(table_name=tbl)
            connector.write_data(df, table_name=tbl)
            print(f"[OK] Successfully seeded table '{tbl}' with {len(df)} rows in PostgreSQL!\n")
        except Exception as e:
            print(f"[ERROR] Failed to seed PostgreSQL table '{tbl}': {e}\n")
            success = False

    return success


if __name__ == "__main__":
    table = os.environ.get("PG_TABLE")
    seed_postgres(table_name=table)

