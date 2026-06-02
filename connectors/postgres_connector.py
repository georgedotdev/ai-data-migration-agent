"""
PostgreSQL Connector

Implements BaseConnector for PostgreSQL databases.
Uses sqlalchemy + psycopg2-binary for database operations.
"""

import pandas as pd
from sqlalchemy import create_engine, text

from connectors.base_connector import BaseConnector


class PostgreSQLConnector(BaseConnector):

    def __init__(
        self,
        host="localhost",
        port=5432,
        database="migration_db",
        username="migration",
        password="migration123",
        table_name="enterprise"
    ):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.table_name = table_name

        self.connection_string = (
            f"postgresql+psycopg2://{username}:{password}"
            f"@{host}:{port}/{database}"
        )
        self.engine = create_engine(self.connection_string)

    def read_data(self):
        """Read entire table into a DataFrame."""

        query = f"SELECT * FROM {self.table_name}"
        df = pd.read_sql(query, self.engine)
        return df

    def write_data(self, df):
        """Write DataFrame to PostgreSQL table (replace if exists)."""

        df.to_sql(
            self.table_name,
            self.engine,
            if_exists="replace",
            index=False
        )
        print(
            f"[PostgreSQL] Wrote {len(df)} rows "
            f"to {self.database}.{self.table_name}"
        )

    def get_schema(self):
        """Retrieve column schema from INFORMATION_SCHEMA."""

        query = text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = :table
            ORDER BY ordinal_position
        """)

        with self.engine.connect() as conn:
            result = conn.execute(
                query, {"table": self.table_name}
            )
            return result.fetchall()

    def drop_table(self):
        """Drop the table — used for rollback."""

        with self.engine.connect() as conn:
            conn.execute(
                text(
                    f"DROP TABLE IF EXISTS {self.table_name}"
                )
            )
            conn.commit()

        print(
            f"[PostgreSQL ROLLBACK] Dropped "
            f"{self.table_name}"
        )

    def count_rows(self):
        """Return row count for validation."""

        query = f"SELECT COUNT(*) FROM {self.table_name}"
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            return result.scalar()
