import pandas as pd


def transform_data(df: pd.DataFrame, transformations=None) -> pd.DataFrame:
    """
    Apply transformations to the dataset.

    If transformations is None, apply all (backward compatible).
    If transformations is a list, apply only the specified ones.

    Supported transformations:
        - normalize_columns
        - handle_nulls
        - type_conversion
    """

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