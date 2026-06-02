import hashlib
import duckdb
import pandas as pd

from etl.extract import extract_csv


def dataframe_checksum(df: pd.DataFrame) -> str:
    """
    Create a deterministic SHA-256 checksum for a DataFrame.
    """
    # Sort columns alphabetically
    df = df.reindex(sorted(df.columns), axis=1)

    # Convert all values to strings
    df = df.astype(str)

    # Sort rows deterministically
    df = df.sort_values(by=list(df.columns)).reset_index(drop=True)

    # Serialize to CSV string
    csv_string = df.to_csv(index=False)

    # Generate SHA-256 hash
    return hashlib.sha256(csv_string.encode("utf-8")).hexdigest()


def validate_migration(
    source_csv: str,
    db_path: str,
    table_name: str
) -> bool:
    """
    Compare checksums of source CSV and DuckDB table.
    Returns True if they match.
    """
    # Read source data
    source_df = extract_csv(source_csv)

    # Apply same transformations as load step
    from etl.transform import transform_data
    source_df = transform_data(source_df)

    # Read target data
    conn = duckdb.connect(db_path)
    target_df = conn.execute(
        f"SELECT * FROM {table_name}"
    ).fetchdf()
    conn.close()

    # Compute checksums
    source_checksum = dataframe_checksum(source_df)
    target_checksum = dataframe_checksum(target_df)

    print(f"Source Checksum: {source_checksum}")
    print(f"Target Checksum: {target_checksum}")

    return source_checksum == target_checksum