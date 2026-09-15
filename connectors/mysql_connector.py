"""
MySQL Connector

Implements BaseConnector for MySQL databases.
Uses sqlalchemy + pymysql for database operations.
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text
from connectors.base_connector import BaseConnector


class MySQLConnector(BaseConnector):
    """Connector for MySQL target database."""

    def __init__(
        self,
        host=None,
        port=None,
        database=None,
        username=None,
        password=None,
        table_name="migrated_data",
        connection_string=None,
        **kwargs
    ):
        self.host = host or os.environ.get("MYSQL_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("MYSQL_PORT", 3306))
        self.database = database or os.environ.get("MYSQL_DATABASE", "migration_db")
        self.username = username or os.environ.get("MYSQL_USER", "root")
        self.password = password or os.environ.get("MYSQL_PASSWORD", "")
        self.table_name = table_name

        env_db_url = os.environ.get("MYSQL_URL")

        if connection_string:
            self.connection_string = connection_string
        elif env_db_url:
            self.connection_string = env_db_url
        else:
            if self.password:
                auth = f"{self.username}:{self.password}"
            else:
                auth = f"{self.username}"
            self.connection_string = (
                f"mysql+pymysql://{auth}@{self.host}:{self.port}/{self.database}"
            )

        self.engine = create_engine(self.connection_string)

    def write_data(self, df: pd.DataFrame, table_name: str = None, if_exists: str = "replace") -> dict:
        """Write a Pandas DataFrame to a named table, creating it if it doesn't exist."""
        target_table = table_name or self.table_name
        df.to_sql(
            target_table,
            self.engine,
            if_exists=if_exists,
            index=False
        )
        print(f"[MySQL] Wrote {len(df)} rows to {self.database}.{target_table}")
        return {
            "status": "success",
            "rows_written": len(df),
            "table_name": target_table
        }

    def read_data(self, table_name: str = None) -> pd.DataFrame:
        """Extract a full table as a Pandas DataFrame."""
        target_table = table_name or self.table_name
        query = f'SELECT * FROM `{target_table}`'
        return pd.read_sql(query, self.engine)

    def extract_table(self, table_name: str = None) -> pd.DataFrame:
        """Alias for read_data to extract full table as DataFrame."""
        return self.read_data(table_name)

    def list_tables(self) -> list:
        """List all available tables in the database."""
        query = text("SHOW TABLES")
        with self.engine.connect() as conn:
            result = conn.execute(query)
            return [row[0] for row in result.fetchall()]

    def get_schema(self, table_name: str = None):
        """Retrieve schema information for the table."""
        target_table = table_name or self.table_name
        query = text("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
            ORDER BY ORDINAL_POSITION
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"schema": self.database, "table": target_table})
            return result.fetchall()

    def drop_table(self, table_name: str = None):
        """Drop the table — used for rollback."""
        target_table = table_name or self.table_name
        with self.engine.connect() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS `{target_table}`"))
            conn.commit()
        print(f"[MySQL ROLLBACK] Dropped {target_table}")

    def count_rows(self, table_name: str = None) -> int:
        """Return row count for validation."""
        target_table = table_name or self.table_name
        query = f"SELECT COUNT(*) FROM `{target_table}`"
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            return result.scalar()
