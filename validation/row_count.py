import duckdb

from etl.extract import extract_csv


def validate_row_count(
    source_csv: str,
    db_path: str,
    table_name: str
) -> bool:

    # Read source data
    source_df = extract_csv(source_csv)

    # Count source rows
    source_count = len(source_df)

    # Connect to DuckDB
    conn = duckdb.connect(db_path)

    # Count target rows
    target_count = conn.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()[0]

    conn.close()

    print(f"Source Rows: {source_count}")
    print(f"Target Rows: {target_count}")

    return source_count == target_count