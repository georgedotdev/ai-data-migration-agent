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
        result_df, log, quarantine = execute_dsl(df, transformations)
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
        tuple: (transformed_df, execution_log, quarantine_report)
    """

    return execute_dsl(df, dsl)


import numpy as np
import re


def run_deterministic_pipeline(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """
    Deterministic rule-based decision tree cleaner that runs without LLMs.

    Applies the following rules in order:
    1. Strip leading/trailing whitespace from all string columns
    2. Standardize column names to lowercase with underscores
    3. For any column where >50% of values are "UNKNOWN", "ERROR", "N/A", or "none" — flag in log, leave values as-is
    4. For string columns with <50% sentinel values — replace "UNKNOWN", "ERROR", "N/A", "none" with NULL
    5. Attempt to parse any object-type column that looks like a date (>60% of non-null values match date patterns) and cast to datetime
    6. Attempt to cast any object-type column that looks fully numeric to float64
    7. For numeric columns, fill NULL values with the column median
    8. For string/categorical columns, fill NULL values with the column mode
    9. Remove fully duplicate rows
    10. For numeric columns, detect outliers using IQR — flag them in the transformation log but do not remove them

    Returns:
        tuple: (cleaned_df, transformation_log)
               where transformation_log is a list of dicts with:
               column, action, detail, rows_affected
    """
    df = df.copy()
    transformation_log = []

    def log_action(column, action, detail, rows_affected=0):
        transformation_log.append({
            "column": str(column),
            "action": str(action),
            "detail": str(detail),
            "rows_affected": int(rows_affected)
        })

    # 1. Strip leading/trailing whitespace from all string columns
    for col in df.columns:
        if df[col].dtype == object or isinstance(df[col].dtype, pd.StringDtype):
            def _strip_val(val):
                return val.strip() if isinstance(val, str) else val

            stripped = df[col].apply(_strip_val)
            # Compare non-null values
            mask = df[col].notna() & (df[col] != stripped)
            affected = int(mask.sum())
            if affected > 0:
                df[col] = stripped
                log_action(col, "strip_whitespace", f"Stripped leading/trailing whitespace from {affected} rows", affected)

    # 2. Standardize column names to lowercase with underscores
    old_cols = list(df.columns)
    new_cols = []
    for col in old_cols:
        cleaned_col = re.sub(r'[^a-zA-Z0-9_]+', '_', str(col).strip()).strip('_').lower()
        if not cleaned_col:
            cleaned_col = "col"
        new_cols.append(cleaned_col)

    # Resolve any potential name collisions
    seen = {}
    unique_new_cols = []
    for c in new_cols:
        if c in seen:
            seen[c] += 1
            unique_new_cols.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            unique_new_cols.append(c)

    for old, new in zip(old_cols, unique_new_cols):
        if old != new:
            log_action(old, "standardize_column_name", f"Renamed column '{old}' -> '{new}'", len(df))

    df.columns = unique_new_cols

    # Sentinel value set for rules 3 and 4
    SENTINELS = {"UNKNOWN", "ERROR", "N/A", "NONE"}

    # 3 & 4. Sentinel values handling
    for col in df.columns:
        if df[col].dtype == object or isinstance(df[col].dtype, pd.StringDtype):
            total_rows = len(df)
            if total_rows > 0:
                is_sentinel = df[col].apply(
                    lambda x: str(x).strip().upper() in SENTINELS if pd.notna(x) else False
                )
                sentinel_count = int(is_sentinel.sum())
                if sentinel_count > 0:
                    ratio = sentinel_count / total_rows
                    if ratio > 0.5:
                        # Rule 3: >50% sentinel values -> flag in log, leave values as-is
                        log_action(
                            col,
                            "flag_high_sentinels",
                            f"More than 50% values ({sentinel_count}/{total_rows}, {ratio:.1%}) are sentinels ('UNKNOWN', 'ERROR', 'N/A', 'none') - values preserved as-is",
                            sentinel_count
                        )
                    else:
                        # Rule 4: <50% sentinel values -> replace with NULL
                        df.loc[is_sentinel, col] = np.nan
                        log_action(
                            col,
                            "replace_sentinels_with_null",
                            f"Replaced {sentinel_count} sentinel values ('UNKNOWN', 'ERROR', 'N/A', 'none') with NULL",
                            sentinel_count
                        )

    # 5. Attempt to parse object-type column that looks like a date (>60% non-null match common date patterns)
    date_regex = re.compile(
        r'^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})(\s+\d{1,2}:\d{2}(:\d{2})?)?$'
    )

    for col in df.columns:
        if df[col].dtype == object:
            non_null = df[col].dropna()
            if len(non_null) > 0:
                match_count = sum(1 for v in non_null if date_regex.match(str(v).strip()))
                if (match_count / len(non_null)) > 0.6:
                    parsed_dt = pd.to_datetime(df[col], errors="coerce")
                    valid_parsed = int(parsed_dt.notna().sum())
                    if valid_parsed > 0:
                        df[col] = parsed_dt
                        log_action(
                            col,
                            "cast_to_datetime",
                            f"Cast column to datetime ({match_count}/{len(non_null)} matched date pattern)",
                            valid_parsed
                        )

    # 6. Attempt to cast any object-type column that looks fully numeric to float64
    for col in df.columns:
        if df[col].dtype == object:
            non_null = df[col].dropna()
            if len(non_null) > 0:
                # Check if all non-null values can be converted to float
                def _is_num(val):
                    try:
                        clean_str = str(val).replace(',', '').strip()
                        float(clean_str)
                        return True
                    except (ValueError, TypeError):
                        return False

                if all(_is_num(v) for v in non_null):
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.strip(), errors='coerce').astype('float64')
                    log_action(
                        col,
                        "cast_to_float64",
                        f"All {len(non_null)} non-null values are numeric - cast to float64",
                        len(non_null)
                    )

    # 7. For numeric columns, fill NULL values with the column median
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                median_val = df[col].median()
                if pd.notna(median_val):
                    df[col] = df[col].fillna(median_val)
                    log_action(
                        col,
                        "fill_null_median",
                        f"Filled {null_count} NULLs with column median ({median_val})",
                        null_count
                    )

    # 8. For string/categorical columns, fill NULL values with the column mode
    for col in df.columns:
        if df[col].dtype == object or isinstance(df[col].dtype, pd.CategoricalDtype) or isinstance(df[col].dtype, pd.StringDtype):
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                modes = df[col].mode()
                if len(modes) > 0:
                    mode_val = modes.iloc[0]
                    df[col] = df[col].fillna(mode_val)
                    log_action(
                        col,
                        "fill_null_mode",
                        f"Filled {null_count} NULLs with column mode ('{mode_val}')",
                        null_count
                    )

    # 9. Remove fully duplicate rows
    rows_before = len(df)
    df = df.drop_duplicates()
    dupes_removed = rows_before - len(df)
    if dupes_removed > 0:
        log_action(
            "ALL_COLUMNS",
            "remove_duplicates",
            f"Removed {dupes_removed} duplicate rows (from {rows_before} to {len(df)})",
            dupes_removed
        )

    # 10. For numeric columns, detect outliers using IQR — flag them in the transformation log but do not remove them
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
            non_null = df[col].dropna()
            if len(non_null) >= 4:
                q25 = float(non_null.quantile(0.25))
                q75 = float(non_null.quantile(0.75))
                iqr = q75 - q25
                if iqr > 0:
                    lower_bound = q25 - 1.5 * iqr
                    upper_bound = q75 + 1.5 * iqr
                    outliers = non_null[(non_null < lower_bound) | (non_null > upper_bound)]
                    outlier_count = len(outliers)
                    if outlier_count > 0:
                        log_action(
                            col,
                            "flag_outliers_iqr",
                            f"Detected {outlier_count} outliers using IQR bounds [{lower_bound:.2f}, {upper_bound:.2f}] (values preserved)",
                            outlier_count
                        )

    # Populate "no action required" for any column that didn't have any transformation recorded
    affected_columns = {entry["column"] for entry in transformation_log}
    for col in df.columns:
        if col not in affected_columns:
            log_action(
                col,
                "no_action_required",
                "Column passed checks without modifications",
                0
            )

    return df, transformation_log