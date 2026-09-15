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


def seed_postgres(table_name="enterprise", csv_filename="messy_ecommerce_sales_data.csv"):
    csv_path = os.path.join(os.path.dirname(__file__), csv_filename)
    if not os.path.exists(csv_path):
        print(f"❌ Sample CSV not found at {csv_path}")
        return False

    print(f"Reading sample data from {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns.")

    print(f"Connecting to PostgreSQL and writing to table '{table_name}'...")
    try:
        connector = PostgreSQLConnector(table_name=table_name)
        connector.write_data(df, table_name=table_name)
        print(f"✅ Successfully seeded table '{table_name}' with {len(df)} rows in PostgreSQL!")
        return True
    except Exception as e:
        print(f"❌ Failed to seed PostgreSQL: {e}")
        return False


if __name__ == "__main__":
    table = os.environ.get("PG_TABLE", "enterprise")
    seed_postgres(table_name=table)
