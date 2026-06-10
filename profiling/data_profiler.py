"""
Data Profiler

Connector-generic data quality profiling engine.
Goes beyond schema discovery (column names, types, nullability)
to calculate deep data quality metrics:

- Missing value counts and percentages per column
- Duplicate counts (per-column uniqueness and full-row duplicates)
- Unique ratios and primary key candidacy
- Structural metadata: nested object/array detection for MongoDB -> Postgres flattening
- Outlier flags for numeric columns (IQR-based)
- Overall data quality score (composite metric)

Usage:
    from profiling.data_profiler import profile_data

    # From a connector
    from connectors.connector_factory import get_connector
    connector = get_connector("csv", file_path="data/enterprise.csv")
    profile = profile_data(connector)

    # From a DataFrame directly
    profile = profile_dataframe(df)
"""

import pandas as pd
import numpy as np
from typing import Optional


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

SAMPLE_LIMIT = 10_000  # Max rows before sampling kicks in
SAMPLE_VALUES_COUNT = 5  # Number of sample values per column
OUTLIER_IQR_MULTIPLIER = 1.5  # Standard IQR multiplier


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def profile_data(connector, sample_limit: int = SAMPLE_LIMIT) -> dict:
    """
    Profile data from any BaseConnector instance.

    Reads data via connector.read_data() and delegates to
    profile_dataframe() for the actual analysis.

    Args:
        connector: Any BaseConnector instance (CSV, DuckDB, PostgreSQL, MongoDB)
        sample_limit: Max rows to profile. If the dataset exceeds this,
                      only the first sample_limit rows are profiled and
                      'is_sampled' is set to True in the output.

    Returns:
        dict: Full profile with column-level metrics and overall quality score.
    """

    df = connector.read_data()

    # Include connector metadata
    profile = profile_dataframe(df, sample_limit=sample_limit)
    profile["connector_type"] = type(connector).__name__

    return profile


def profile_dataframe(
    df: pd.DataFrame,
    sample_limit: int = SAMPLE_LIMIT
) -> dict:
    """
    Profile a pandas DataFrame for data quality metrics.

    This is the core profiling engine. It can be called directly
    with a DataFrame (useful for testing and re-profiling after
    transformations).

    Args:
        df: The DataFrame to profile.
        sample_limit: Max rows to analyze. Larger datasets are sampled.

    Returns:
        dict with:
            - row_count: Total rows in the original DataFrame
            - column_count: Number of columns
            - is_sampled: Whether profiling used a sample
            - sampled_rows: Number of rows actually profiled
            - duplicate_rows: Count of fully duplicated rows
            - columns: Dict of column_name -> column profile
            - data_quality_score: Composite quality score (0-100)
    """

    total_rows = len(df)
    is_sampled = total_rows > sample_limit

    # Sample if necessary (preserve original for row_count reporting)
    if is_sampled:
        df_profile = df.head(sample_limit).copy()
    else:
        df_profile = df.copy()

    sampled_rows = len(df_profile)

    # ─── Full-row duplicate detection ───
    # pandas .duplicated() fails on columns with unhashable types
    # (dicts, lists from MongoDB). Gracefully skip in that case.
    try:
        duplicate_rows = int(df_profile.duplicated().sum())
    except TypeError:
        duplicate_rows = 0

    # ─── Column-level profiling ───
    columns = {}
    quality_penalties = []

    for col_name in df_profile.columns:
        col_profile = _profile_column(df_profile[col_name], sampled_rows)
        columns[col_name] = col_profile

        # Accumulate quality penalties
        quality_penalties.append(col_profile.get("missing_pct", 0))

    # ─── Data Quality Score ───
    data_quality_score = _compute_quality_score(
        columns, duplicate_rows, sampled_rows
    )

    return {
        "row_count": total_rows,
        "column_count": len(df_profile.columns),
        "is_sampled": is_sampled,
        "sampled_rows": sampled_rows,
        "duplicate_rows": duplicate_rows,
        "columns": columns,
        "data_quality_score": round(data_quality_score, 2)
    }


# ─────────────────────────────────────────────
# Column-Level Profiling
# ─────────────────────────────────────────────

def _profile_column(series: pd.Series, total_rows: int) -> dict:
    """
    Profile a single column (pandas Series).

    Returns a dict with metrics covering:
    - Data type and structural type (flat, nested_object, nested_array)
    - Missing values (count + percentage)
    - Uniqueness (count, percentage, primary key candidacy)
    - Duplicate count
    - Sample values
    - Outlier info for numeric columns
    - Nested structure metadata for object columns
    """

    col_name = series.name
    dtype = str(series.dtype)

    # ─── Missing values ───
    missing_count = int(series.isna().sum())
    missing_pct = round(
        (missing_count / total_rows * 100) if total_rows > 0 else 0, 2
    )

    # ─── Uniqueness ───
    # pandas nunique() fails on columns with unhashable types
    # (dicts, lists from MongoDB). Gracefully degrade.
    non_null = series.dropna()
    try:
        unique_count = int(non_null.nunique())
        unique_pct = round(
            (unique_count / len(non_null) * 100) if len(non_null) > 0 else 0, 2
        )
        duplicate_count = int(len(non_null) - unique_count)
    except TypeError:
        unique_count = 0
        unique_pct = 0.0
        duplicate_count = 0

    # ─── Primary key candidacy ───
    is_potential_pk = (
        missing_count == 0
        and unique_count == total_rows
        and unique_count > 0
        and total_rows > 0
    )

    # ─── Sample values ───
    sample_values = _get_sample_values(non_null)

    # ─── Structural type detection ───
    structural_info = _detect_structural_type(non_null)

    # ─── Outlier detection (numeric only) ───
    outlier_info = _detect_outliers(series)

    # ─── Sentinel detection ───
    suspected_sentinels = _detect_sentinels(non_null)

    # ─── Build profile ───
    profile = {
        "dtype": dtype,
        "structural_type": structural_info["structural_type"],
        "missing_count": missing_count,
        "missing_pct": missing_pct,
        "unique_count": unique_count,
        "unique_pct": unique_pct,
        "duplicate_count": duplicate_count,
        "is_potential_pk": is_potential_pk,
        "sample_values": sample_values,
        "suspected_sentinels": suspected_sentinels
    }

    # Add nested structure metadata if applicable
    if structural_info["structural_type"] != "flat":
        profile["nested_keys"] = structural_info.get("nested_keys", [])
        profile["nested_depth"] = structural_info.get("nested_depth", 0)

    # Add numeric statistics if applicable
    if outlier_info:
        profile["numeric_stats"] = outlier_info

    return profile


# ─────────────────────────────────────────────
# Sentinel Value Detection
# ─────────────────────────────────────────────

def _detect_sentinels(series: pd.Series) -> list:
    """
    Detect suspected sentinel values like 'ERROR' or 'UNKNOWN'.
    Only applies to categorical/string columns.
    """
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return []
        
    COMMON_SENTINELS = {"ERROR", "UNKNOWN", "N/A", "MISSING", "999", "NULL", "NONE", "NA", "UNDEFINED"}
    
    try:
        # Check the unique string values against our common sentinels set
        unique_vals = series.unique()
        found_sentinels = []
        for val in unique_vals:
            if isinstance(val, str) and val.strip().upper() in COMMON_SENTINELS:
                found_sentinels.append(val)
        return found_sentinels
    except TypeError:
        return []

# ─────────────────────────────────────────────
# Structural Type Detection
# ─────────────────────────────────────────────

def _detect_structural_type(series: pd.Series) -> dict:
    """
    Detect whether a column contains flat values, nested objects (dicts),
    or nested arrays (lists).

    This is critical for MongoDB -> PostgreSQL migrations where nested
    documents need to be flattened.

    Samples up to 100 non-null values to determine the dominant type.
    """

    if len(series) == 0:
        return {"structural_type": "flat"}

    # Sample for performance
    sample = series.head(100)

    dict_count = 0
    list_count = 0
    all_nested_keys = set()
    max_depth = 0

    for value in sample:
        if isinstance(value, dict):
            dict_count += 1
            all_nested_keys.update(value.keys())
            depth = _get_dict_depth(value)
            max_depth = max(max_depth, depth)
        elif isinstance(value, list):
            list_count += 1

    total_checked = len(sample)

    # If >50% of values are dicts, it's a nested object column
    if dict_count > total_checked * 0.5:
        return {
            "structural_type": "nested_object",
            "nested_keys": sorted(all_nested_keys),
            "nested_depth": max_depth
        }

    # If >50% of values are lists, it's a nested array column
    if list_count > total_checked * 0.5:
        return {
            "structural_type": "nested_array",
            "nested_keys": [],
            "nested_depth": 1
        }

    return {"structural_type": "flat"}


def _get_dict_depth(d: dict, current_depth: int = 1) -> int:
    """Recursively compute the nesting depth of a dict."""

    if not isinstance(d, dict) or not d:
        return current_depth

    max_child = current_depth
    for value in d.values():
        if isinstance(value, dict):
            child_depth = _get_dict_depth(value, current_depth + 1)
            max_child = max(max_child, child_depth)

    return max_child


# ─────────────────────────────────────────────
# Outlier Detection (Numeric Columns)
# ─────────────────────────────────────────────

def _detect_outliers(series: pd.Series) -> Optional[dict]:
    """
    Detect outliers in numeric columns using the IQR method.

    Returns None for non-numeric columns.
    Returns a dict with min, max, mean, median, std, Q1, Q3,
    IQR bounds, and outlier count for numeric columns.
    """

    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return None

    clean = series.dropna()

    if len(clean) == 0:
        return None

    try:
        q1 = float(clean.quantile(0.25))
        q3 = float(clean.quantile(0.75))
        iqr = q3 - q1
        lower_bound = q1 - OUTLIER_IQR_MULTIPLIER * iqr
        upper_bound = q3 + OUTLIER_IQR_MULTIPLIER * iqr

        outlier_count = int(
            ((clean < lower_bound) | (clean > upper_bound)).sum()
        )

        return {
            "min": float(clean.min()),
            "max": float(clean.max()),
            "mean": round(float(clean.mean()), 4),
            "median": float(clean.median()),
            "std": round(float(clean.std()), 4),
            "q1": q1,
            "q3": q3,
            "iqr": round(iqr, 4),
            "lower_bound": round(lower_bound, 4),
            "upper_bound": round(upper_bound, 4),
            "outlier_count": outlier_count,
            "outlier_pct": round(
                (outlier_count / len(clean) * 100) if len(clean) > 0 else 0, 2
            )
        }
    except (TypeError, ValueError, NotImplementedError):
        return None


# ─────────────────────────────────────────────
# Sample Values
# ─────────────────────────────────────────────

def _get_sample_values(series: pd.Series) -> list:
    """
    Extract up to SAMPLE_VALUES_COUNT representative sample values.

    Tries to pick unique values for diversity.
    Converts all values to JSON-serializable types.
    """

    if len(series) == 0:
        return []

    # series.unique() fails on unhashable types (dicts, lists).
    # Fall back to head() for those columns.
    try:
        unique_vals = series.unique()
        samples = unique_vals[:SAMPLE_VALUES_COUNT]
    except TypeError:
        samples = series.head(SAMPLE_VALUES_COUNT).values

    result = []
    for val in samples:
        result.append(_to_serializable(val))

    return result


def _to_serializable(value):
    """Convert a value to a JSON-serializable type."""

    if isinstance(value, (np.integer,)):
        return int(value)
    elif isinstance(value, (np.floating,)):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    elif isinstance(value, (np.ndarray,)):
        return value.tolist()
    elif isinstance(value, (dict, list)):
        return value
    elif pd.isna(value):
        return None
    else:
        return str(value)


# ─────────────────────────────────────────────
# Data Quality Score
# ─────────────────────────────────────────────

def _compute_quality_score(
    columns: dict,
    duplicate_rows: int,
    total_rows: int
) -> float:
    """
    Compute a composite data quality score (0-100).

    Scoring methodology:
    - Starts at 100
    - Penalty for missing values: avg missing_pct across columns (weight: 0.4)
    - Penalty for duplicates: duplicate_rows / total_rows * 100 (weight: 0.3)
    - Penalty for low uniqueness: avg (100 - unique_pct) for non-PK cols (weight: 0.15)
    - Penalty for outliers: avg outlier_pct across numeric cols (weight: 0.15)

    The result is clamped to [0, 100].
    """

    if not columns or total_rows == 0:
        return 0.0

    # Missing values penalty
    missing_pcts = [
        col["missing_pct"] for col in columns.values()
    ]
    avg_missing = sum(missing_pcts) / len(missing_pcts)

    # Duplicate rows penalty
    duplicate_pct = (duplicate_rows / total_rows * 100)

    # Low uniqueness penalty (for non-PK columns)
    non_pk_unique_pcts = [
        col["unique_pct"] for col in columns.values()
        if not col.get("is_potential_pk", False)
    ]
    avg_low_uniqueness = (
        sum(100 - u for u in non_pk_unique_pcts) / len(non_pk_unique_pcts)
        if non_pk_unique_pcts else 0
    )

    # Outlier penalty (numeric columns only)
    outlier_pcts = [
        col["numeric_stats"]["outlier_pct"]
        for col in columns.values()
        if col.get("numeric_stats")
    ]
    avg_outlier = (
        sum(outlier_pcts) / len(outlier_pcts)
        if outlier_pcts else 0
    )

    # Weighted composite
    score = 100.0
    score -= avg_missing * 0.4
    score -= duplicate_pct * 0.3
    score -= avg_low_uniqueness * 0.15
    score -= avg_outlier * 0.15

    return max(0.0, min(100.0, score))
