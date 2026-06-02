"""
Schema Discovery

Connector-generic schema discovery. Works for any source connector.
Backward compatible: accepts file paths (treats as CSV).
"""

import pandas as pd

from connectors.connector_factory import get_connector


def discover_schema(source_type="csv", source_config=None):
    """
    Discover schema information from any source connector.

    Args:
        source_type: Connector type string ('csv', 'postgresql', 'mongodb')
                     OR a file path string (backward compatible — treated as CSV)
        source_config: Dict of connection parameters for the connector.
                       If source_type is a file path, this is ignored.

    Returns:
        dict with table_name, row_count, column_count, columns, primary_key_candidates
    """

    # Backward compatibility: if source_type looks like a file path
    if source_config is None and (
        source_type.endswith(".csv") or "/" in source_type or "\\" in source_type
    ):
        file_path = source_type
        source_type = "csv"
        source_config = {"file_path": file_path}

    if source_config is None:
        source_config = {}

    # Build connector and read data
    source = get_connector(source_type, **source_config)
    df = source.read_data()

    # Analyze columns
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

    # Determine table name for display
    if source_type == "csv":
        display_name = source_config.get("file_path", "unknown")
    elif source_type in ("postgresql", "mongodb"):
        display_name = source_config.get(
            "table_name",
            source_config.get("collection", "unknown")
        )
    else:
        display_name = "unknown"

    return {
        "table_name": display_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
        "primary_key_candidates": primary_key_candidates
    }