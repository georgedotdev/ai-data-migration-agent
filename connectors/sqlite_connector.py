"""
SQLite Connector

Implements BaseConnector for a SQLite database file (source or target).
"""

import os

import pandas as pd
from sqlalchemy import text

from connectors.base_connector import BaseConnector
from etl.endpoints import Endpoint


class SQLiteConnector(BaseConnector):

    def __init__(self, db_path="runtime/target.sqlite", table_name="migrated_data", **kwargs):
        self.db_path = os.path.abspath(db_path)
        self.endpoint = Endpoint("sqlite", {"path": self.db_path})
        self.table_name = self.endpoint.dialect.q(table_name).strip('"')   # validates the identifier
        self.engine = self.endpoint.engine()

    def read_data(self, table_name=None):
        return self.endpoint.read_table(table_name or self.table_name)

    def write_data(self, df: pd.DataFrame, table_name=None, if_exists="replace"):
        target = table_name or self.table_name
        df.to_sql(target, self.engine, if_exists=if_exists, index=False, chunksize=1000)
        return {"status": "success", "rows_written": len(df), "table_name": target}

    def get_schema(self):
        with self.engine.connect() as conn:
            return conn.execute(text(f"PRAGMA table_info({self.endpoint.dialect.q(self.table_name)})")).fetchall()

    def drop_table(self):
        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {self.endpoint.dialect.q(self.table_name)}"))

    def count_rows(self):
        return self.endpoint.count(self.table_name)
