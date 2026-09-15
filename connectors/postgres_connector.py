"""
PostgreSQL Connector

Implements BaseConnector for PostgreSQL databases.
Uses sqlalchemy + psycopg2 for database operations.
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text
from connectors.base_connector import BaseConnector


class PostgreSQLConnector(BaseConnector):
    """Connector for PostgreSQL source/target database."""

    def __init__(
        self,
        host=None,
        port=None,
        database=None,
        username=None,
        password=None,
        table_name="enterprise",
        connection_string=None,
        **kwargs
    ):
        # Support both PG_* (standard/prompt) and legacy DB_* environment variables
        self.host = host or os.environ.get("PG_HOST") or os.environ.get("DB_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("PG_PORT") or os.environ.get("DB_PORT", "5432"))
        self.database = database or os.environ.get("PG_DATABASE") or os.environ.get("DB_DATABASE", "migration_db")
        self.username = username or os.environ.get("PG_USER") or os.environ.get("DB_USER", "postgres")
        self.password = password or os.environ.get("PG_PASSWORD") or os.environ.get("DB_PASSWORD", "")
        self.table_name = table_name

        env_db_url = os.environ.get("DATABASE_URL") or os.environ.get("PG_URL")

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
                f"postgresql://{auth}@{self.host}:{self.port}/{self.database}"
            )

        self.engine = create_engine(self.connection_string)

    def list_tables(self) -> list:
        """List available user tables in the public schema."""
        query = text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query)
            return [row[0] for row in result.fetchall()]

    def read_data(self, table_name: str = None) -> pd.DataFrame:
        """Read entire table into a DataFrame."""
        target_table = table_name or self.table_name
        query = f'SELECT * FROM "{target_table}"'
        df = pd.read_sql(query, self.engine)
        return df

    def extract_table(self, table_name: str = None) -> pd.DataFrame:
        """Extract a full table as a Pandas DataFrame."""
        return self.read_data(table_name)

    def write_data(self, df: pd.DataFrame, table_name: str = None, if_exists: str = "replace") -> dict:
        """Write DataFrame to PostgreSQL table (replace if exists)."""
        target_table = table_name or self.table_name
        df.to_sql(
            target_table,
            self.engine,
            if_exists=if_exists,
            index=False
        )
        print(
            f"[PostgreSQL] Wrote {len(df)} rows "
            f"to {self.database}.{target_table}"
        )
        return {
            "status": "success",
            "rows_written": len(df),
            "table_name": target_table
        }

    def get_schema(self, table_name: str = None):
        """Retrieve column schema from INFORMATION_SCHEMA."""
        target_table = table_name or self.table_name
        query = text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = :table
            ORDER BY ordinal_position
        """)

        with self.engine.connect() as conn:
            result = conn.execute(
                query, {"table": target_table}
            )
            return result.fetchall()

    def drop_table(self, table_name: str = None):
        """Drop the table — used for rollback."""
        target_table = table_name or self.table_name
        with self.engine.connect() as conn:
            conn.execute(
                text(
                    f'DROP TABLE IF EXISTS "{target_table}"'
                )
            )
            conn.commit()

        print(
            f"[PostgreSQL ROLLBACK] Dropped "
            f"{target_table}"
        )

    def count_rows(self, table_name: str = None) -> int:
        """Return row count for validation."""
        target_table = table_name or self.table_name
        query = f'SELECT COUNT(*) FROM "{target_table}"'
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            return result.scalar()
