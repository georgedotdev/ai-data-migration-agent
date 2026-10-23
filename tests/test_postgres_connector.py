"""
Test: PostgreSQL Connector

Verifies CSV → PostgreSQL → Read Back.

Requires a running PostgreSQL instance. Connection settings come from the
PG_* environment variables; the defaults match docker-compose.yml:
  docker compose up -d postgres
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from connectors.csv_connector import CSVConnector
from connectors.postgres_connector import PostgreSQLConnector


def test_csv_to_postgres():
    # Read CSV source
    source = CSVConnector("data/enterprise.csv")
    source_df = source.read_data()
    print(f"Source rows: {len(source_df)}")
    print(f"Source columns: {list(source_df.columns)}")

    # Write to PostgreSQL
    target = PostgreSQLConnector(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        database=os.environ.get("PG_DATABASE", "migration_db"),
        username=os.environ.get("PG_USER", "postgres"),
        password=os.environ.get("PG_PASSWORD", "postgres"),
        table_name="enterprise_test"
    )
    try:
        with target.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("PostgreSQL is not reachable")

    target.write_data(source_df)

    # Read back
    result_df = target.read_data()
    print(f"Target rows: {len(result_df)}")

    # Validate
    assert len(source_df) == len(result_df), (
        f"Row count mismatch: {len(source_df)} vs {len(result_df)}"
    )

    # Count rows
    count = target.count_rows()
    print(f"count_rows(): {count}")
    assert count == len(source_df)

    # Schema
    schema = target.get_schema()
    print(f"Schema columns: {len(schema)}")

    # Cleanup
    target.drop_table()
    print("Cleanup complete")

    print("\n✅ PostgreSQL connector test PASSED")


if __name__ == "__main__":
    test_csv_to_postgres()
