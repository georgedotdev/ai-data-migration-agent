"""
Test: MongoDB Connector

Verifies CSV → MongoDB → Read Back.

Requires a running MongoDB instance.
Default: mongodb://localhost:27017

Docker setup:
  docker run -d --name migration-mongo \
    -p 27017:27017 \
    mongo:7
"""

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from connectors.csv_connector import CSVConnector
from connectors.mongodb_connector import MongoDBConnector


def test_csv_to_mongodb():
    # Read CSV source
    source = CSVConnector("data/enterprise.csv")
    source_df = source.read_data()
    print(f"Source rows: {len(source_df)}")
    print(f"Source columns: {list(source_df.columns)}")

    # Write to MongoDB
    target = MongoDBConnector(
        connection_string="mongodb://localhost:27017/?serverSelectionTimeoutMS=1000",
        database="migration_test",
        collection="enterprise_test"
    )
    try:
        target.client.admin.command("ping")
    except ServerSelectionTimeoutError:
        pytest.skip("MongoDB is not running on localhost:27017")

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
    print(f"Schema fields: {len(schema)}")

    # Cleanup
    target.drop_table()
    print("Cleanup complete")

    print("\n✅ MongoDB connector test PASSED")


if __name__ == "__main__":
    test_csv_to_mongodb()
