"""
Row Count Validation

Connector-generic row count comparison.
Uses connector instances instead of hardcoded CSV/DuckDB calls.
"""


def validate_row_count(
    source_connector,
    target_connector
) -> bool:
    """
    Verify source and target row counts match.

    Uses count_rows() from connector instances —
    works for CSV, DuckDB, PostgreSQL, MongoDB.
    """

    source_count = source_connector.count_rows()
    target_count = target_connector.count_rows()

    print(f"Source Rows: {source_count}")
    print(f"Target Rows: {target_count}")

    return source_count == target_count