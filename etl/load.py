import duckdb
import pandas as pd


def load_to_duckdb(df: pd.DataFrame, db_path:str, table_name:str) -> None:

    conn = duckdb.connect(db_path)

    conn.register("temp_df",df)

    conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM temp_df")

    conn.close()