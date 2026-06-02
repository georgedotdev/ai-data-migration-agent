import duckdb

from connectors.base_connector import BaseConnector


class DuckDBConnector(BaseConnector):

    def __init__(
        self,
        db_path,
        table_name
    ):

        self.db_path = db_path
        self.table_name = table_name

    def read_data(self):

        conn = duckdb.connect(self.db_path)

        df = conn.execute(
            f"SELECT * FROM {self.table_name}"
        ).df()

        conn.close()

        return df

    def write_data(self, df):

        conn = duckdb.connect(self.db_path)

        conn.register(
            "temp_df",
            df
        )

        conn.execute(
            f"""
            CREATE OR REPLACE TABLE
            {self.table_name}
            AS SELECT * FROM temp_df
            """
        )

        conn.close()

    def get_schema(self):

        conn = duckdb.connect(self.db_path)

        schema = conn.execute(
            f"DESCRIBE {self.table_name}"
        ).fetchall()

        conn.close()

        return schema