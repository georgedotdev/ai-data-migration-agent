"""
Row Count Validation

Connector-generic row count comparison.
Uses connector instances instead of hardcoded CSV/DuckDB calls.
"""


from etl.transform import transform_data, transform_data_dsl

def validate_row_count(
    source_connector,
    target_connector,
    dsl_transformations=None,
    transformations=None
) -> bool:
    """
    Verify source and target row counts match.

    Uses connector instances — works for CSV, DuckDB, PostgreSQL, MongoDB.
    If transformations are specified, applies them in memory first to get
    the accurate post-transformation row count.
    """
    
    target_count = target_connector.count_rows()

    if dsl_transformations or transformations:
        # Transformation-aware row count
        df = source_connector.read_data()
        if dsl_transformations:
            df, _ = transform_data_dsl(df, dsl_transformations)
        elif transformations:
            df = transform_data(df, transformations=transformations)
        source_count = len(df)
    else:
        # Optimized native count
        source_count = source_connector.count_rows()

    print(f"Source Rows (Post-transform): {source_count}")
    print(f"Target Rows: {target_count}")

    return source_count == target_count