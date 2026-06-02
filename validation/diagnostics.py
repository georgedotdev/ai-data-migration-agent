"""
Validation Diagnostics

Connector-generic cell-level mismatch detection.
Uses connector instances instead of hardcoded CSV/DuckDB calls.

When validation fails, this module pinpoints the exact rows,
columns, and values where source and target data diverge.

Produces a structured mismatch report capped at N entries
so large datasets remain manageable.
"""

import pandas as pd

from etl.transform import transform_data


def run_diagnostics(
    source_connector,
    target_connector,
    transformations=None,
    max_mismatches=20
):
    """
    Compare source and target DataFrames cell-by-cell.

    Uses connector instances — works for any source/target
    combination (CSV, DuckDB, PostgreSQL, MongoDB).

    Returns a structured diagnostics report.
    """

    # Read source data via connector and apply transforms
    source_df = source_connector.read_data()
    source_df = transform_data(
        source_df, transformations=transformations
    )

    # Read target data via connector
    target_df = target_connector.read_data()

    # Initialize report
    report = {
        "source_rows": len(source_df),
        "target_rows": len(target_df),
        "columns_only_in_source": sorted(
            set(source_df.columns) - set(target_df.columns)
        ),
        "columns_only_in_target": sorted(
            set(target_df.columns) - set(source_df.columns)
        ),
        "mismatched_columns": [],
        "total_mismatches_found": 0,
        "total_mismatches_shown": 0,
        "mismatches": []
    }

    # Row count difference
    if len(source_df) != len(target_df):
        report["row_count_mismatch"] = {
            "source": len(source_df),
            "target": len(target_df),
            "difference": abs(
                len(source_df) - len(target_df)
            )
        }

    # Cell-by-cell comparison on common columns
    common_columns = sorted(
        set(source_df.columns) & set(target_df.columns)
    )

    min_rows = min(len(source_df), len(target_df))
    mismatches = []
    mismatched_columns = set()
    total_found = 0

    for col in common_columns:
        source_col = (
            source_df[col]
            .head(min_rows)
            .astype(str)
            .reset_index(drop=True)
        )
        target_col = (
            target_df[col]
            .head(min_rows)
            .astype(str)
            .reset_index(drop=True)
        )

        diff_mask = source_col != target_col
        diff_indices = diff_mask[diff_mask].index.tolist()

        total_found += len(diff_indices)

        for idx in diff_indices:
            if len(mismatches) >= max_mismatches:
                break

            mismatches.append({
                "column": col,
                "row": int(idx),
                "source_value": str(
                    source_col.iloc[idx]
                ),
                "target_value": str(
                    target_col.iloc[idx]
                )
            })
            mismatched_columns.add(col)

        if len(mismatches) >= max_mismatches:
            break

    report["mismatched_columns"] = sorted(mismatched_columns)
    report["total_mismatches_found"] = total_found
    report["total_mismatches_shown"] = len(mismatches)
    report["mismatches"] = mismatches

    return report
