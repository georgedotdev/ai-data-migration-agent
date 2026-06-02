"""
Test: PostgreSQL Connector

Verifies CSV → PostgreSQL → Read Back.

Requires a running PostgreSQL instance.
Default: localhost:5432, db=migration_db, user=migration, password=migration123

Docker setup:
  docker run -d --name migration-pg \
    -e POSTGRES_USER=migration \
    -e POSTGRES_PASSWORD=migration123 \
    -e POSTGRES_DB=migration_db \
    -p 5432:5432 \
    postgres:16
"""

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
        host="localhost",
        port=5432,
        database="migration_db",
        username="migration",
        password="migration123",
        table_name="enterprise_test"
    )
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
