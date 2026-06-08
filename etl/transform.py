"""
Transformation Module

V1 transform_data() is preserved for backward compatibility.
V2 adds transform_data_dsl() which bridges V1 string lists
to the new DSL engine, and also accepts raw DSL dicts.

All existing callers (graph.py, validate.py, diagnostics.py)
continue to work with zero changes.
"""

import pandas as pd

from etl.dsl_engine import execute_dsl


def transform_data(df: pd.DataFrame, transformations=None) -> pd.DataFrame:
    """
    Apply transformations to the dataset.

    If transformations is None, apply all (backward compatible).
    If transformations is a list of strings, apply V1 logic.
    If transformations is a dict with "transformations" key, delegate to DSL engine.

    Supported V1 transformations:
        - normalize_columns
        - handle_nulls
        - type_conversion
    """

    # V2 path: if a DSL dict is passed, delegate to DSL engine
    if isinstance(transformations, dict) and "transformations" in transformations:
        result_df, log = execute_dsl(df, transformations)
        return result_df

    # V1 path: original logic preserved below

    # Create a copy
    df = df.copy()

    # Default: apply all
    if transformations is None:
        transformations = [
            "normalize_columns",
            "handle_nulls",
            "type_conversion"
        ]

    # -----------------------------
    # 1. Rename columns
    # -----------------------------
    if "normalize_columns" in transformations:
        df.columns = [col.lower() for col in df.columns]

        # Example rename
        if "customername" in df.columns:
            df.rename(columns={
                "customername": "customer_name"
            }, inplace=True)

    # -----------------------------
    # 2. Handle null values
    # -----------------------------
    if "handle_nulls" in transformations:
        for column in df.columns:

            if df[column].dtype == "object":
                df[column] = df[column].fillna("UNKNOWN")

            elif "float" in str(df[column].dtype):
                df[column] = df[column].fillna(0.0)

            elif "int" in str(df[column].dtype):
                df[column] = df[column].fillna(0)

    # -----------------------------
    # 3. Type conversion
    # -----------------------------
    if "type_conversion" in transformations:
        if "revenue" in df.columns:
            df["revenue"] = df["revenue"].astype(float)

    return df


def transform_data_dsl(
    df: pd.DataFrame,
    dsl: dict
) -> tuple:
    """
    V2 DSL-based transformation entry point.

    Thin wrapper around execute_dsl that provides a consistent
    interface for the V2 LangGraph workflow.

    Args:
        df: Input DataFrame
        dsl: DSL dict with "transformations" key

    Returns:
        tuple: (transformed_df, execution_log)
    """

    return execute_dsl(df, dsl)