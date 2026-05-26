import pandas as pd


def transform_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply basic transformations to the dataset.
    """

    # Create a copy
    df = df.copy()

    # -----------------------------
    # 1. Rename columns
    # -----------------------------
    df.columns = [col.lower() for col in df.columns]

    # Example rename
    if "customername" in df.columns:
        df.rename(columns={
            "customername": "customer_name"
        }, inplace=True)

    # -----------------------------
    # 2. Handle null values
    # -----------------------------
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
    if "revenue" in df.columns: 
        df["revenue"] = df["revenue"].astype(float)

    return df