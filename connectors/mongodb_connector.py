"""
MongoDB Connector

Implements BaseConnector for MongoDB.
Uses pymongo for database operations.
"""

import pandas as pd
from pymongo import MongoClient

from connectors.base_connector import BaseConnector


import os

class MongoDBConnector(BaseConnector):

    def __init__(
        self,
        connection_string=None,
        database="migration_db",
        collection="enterprise"
    ):
        env_mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        self.connection_string = connection_string or env_mongo_uri
        self.database_name = database
        self.collection_name = collection

        conn_str = self.connection_string
        if "localhost" not in conn_str and "127.0.0.1" not in conn_str:
            if "?" not in conn_str:
                conn_str += "?tls=true"
            elif "tls=true" not in conn_str.lower():
                conn_str += "&tls=true"

        self.client = MongoClient(conn_str, serverSelectionTimeoutMS=5000)
        self.db = self.client[database]
        self.collection = self.db[collection]

    def read_data(self):
        """Read entire collection into a DataFrame."""

        cursor = self.collection.find({}, {"_id": 0})
        documents = list(cursor)

        if not documents:
            return pd.DataFrame()

        df = pd.DataFrame(documents)
        return df

    def write_data(self, df):
        """Write DataFrame to MongoDB collection (replace)."""

        # Drop existing collection
        self.collection.drop()

        # Convert DataFrame to list of dicts
        records = df.to_dict(orient="records")

        if records:
            self.collection.insert_many(records)

        print(
            f"[MongoDB] Wrote {len(records)} documents "
            f"to {self.database_name}.{self.collection_name}"
        )

    def get_schema(self):
        """Infer schema from sample documents."""

        # Sample up to 100 documents
        sample = list(
            self.collection.find({}, {"_id": 0}).limit(100)
        )

        if not sample:
            return []

        # Infer schema from all sampled documents
        field_types = {}

        for doc in sample:
            for key, value in doc.items():
                if key not in field_types:
                    field_types[key] = set()
                field_types[key].add(type(value).__name__)

        schema = []
        for field, types in field_types.items():
            schema.append((
                field,
                ", ".join(sorted(types)),
                "YES"  # MongoDB fields are always nullable
            ))

        return schema

    def drop_table(self):
        """Drop the collection — used for rollback."""

        self.collection.drop()
        print(
            f"[MongoDB ROLLBACK] Dropped collection "
            f"{self.collection_name}"
        )

    def count_rows(self):
        """Return document count for validation."""

        return self.collection.count_documents({})
