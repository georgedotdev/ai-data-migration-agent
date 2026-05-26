import pandas as pd

from etl.extract import extract_csv


def discover_schema(file_path: str) -> dict:
    """
    Discover schema information from a CSV file.
    """

    df = extract_csv(file_path)

    columns = []

    for column in df.columns:

        column_info = {
            "name": column,
            "dtype": str(df[column].dtype),
            "nullable": bool(df[column].isnull().any()),
            "unique": bool(df[column].is_unique)
        }

        columns.append(column_info)

    # Detect possible primary keys
    primary_key_candidates = []

    for column in columns:
        if column["unique"] and not column["nullable"]:
            primary_key_candidates.append(column["name"])

    return {
        "table_name": file_path,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
        "primary_key_candidates": primary_key_candidates
    }