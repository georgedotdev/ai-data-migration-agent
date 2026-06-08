"""
Checksum Validation

Connector-generic checksum comparison. Uses source and target
connector instances instead of hardcoded CSV/DuckDB calls.

The dataframe_checksum() function is already connector-agnostic
since it operates on DataFrames.
"""

import hashlib
import pandas as pd

from connectors.csv_connector import CSVConnector
from connectors.duckdb_connector import DuckDBConnector
from etl.transform import transform_data, transform_data_dsl


def dataframe_checksum(df: pd.DataFrame) -> str:
    """
    Create a deterministic SHA-256 checksum for a DataFrame.
    """
    # Sort columns alphabetically
    df = df.reindex(sorted(df.columns), axis=1)

    # Convert all values to strings
    df = df.astype(str)

    # Sort rows deterministically
    df = df.sort_values(
        by=list(df.columns)
    ).reset_index(drop=True)

    # Serialize to CSV string
    csv_string = df.to_csv(index=False)

    # Generate SHA-256 hash
    return hashlib.sha256(
        csv_string.encode("utf-8")
    ).hexdigest()


def validate_migration(
    source_connector,
    target_connector,
    transformations=None,
    dsl_transformations=None
) -> bool:
    """
    Compare checksums of source and target data.

    Uses connector instances — works for any source/target
    combination (CSV, DuckDB, PostgreSQL, MongoDB).

    Returns True if checksums match.
    """

    source_connector, target_connector, transformations = _coerce_legacy_inputs(
        source_connector,
        target_connector,
        transformations
    )

    # Read source data via connector
    source_df = source_connector.read_data()

    # Apply same transformations as load step
    if dsl_transformations:
        source_df, _ = transform_data_dsl(source_df, dsl_transformations)
    else:
        source_df = transform_data(
            source_df, transformations=transformations
        )

    # Read target data via connector
    target_df = target_connector.read_data()

    # Compute checksums
    source_checksum = dataframe_checksum(source_df)
    target_checksum = dataframe_checksum(target_df)

    print(f"Source Checksum: {source_checksum}")
    print(f"Target Checksum: {target_checksum}")

    return source_checksum == target_checksum


def _coerce_legacy_inputs(
    source_connector,
    target_connector,
    transformations=None
):
    """
    Support the old validate_migration(csv_path, duckdb_path, table_name)
    calling style while preserving connector-based validation.
    """

    if hasattr(source_connector, "read_data") and hasattr(target_connector, "read_data"):
        return source_connector, target_connector, transformations

    if isinstance(source_connector, str) and isinstance(target_connector, str):
        table_name = transformations if isinstance(transformations, str) else "enterprise"
        return (
            CSVConnector(source_connector),
            DuckDBConnector(target_connector, table_name),
            None,
        )

    return source_connector, target_connector, transformations
