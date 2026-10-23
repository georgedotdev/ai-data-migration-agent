"""
Transformation Preview and Impact Engine

Generates step-by-step previews of data transformations and computes
the overall migration impact and risk assessment.
"""

import re

import pandas as pd
from etl.dsl_engine import execute_dsl
from profiling.data_profiler import profile_dataframe

def generate_preview(df: pd.DataFrame, dsl: dict) -> list:
    """
    Simulates the DSL execution step-by-step to capture 
    'Before' and 'After' value examples for transparency.
    """
    df_current = df.copy()
    previews = []
    column_mapping = {}

    transformations = dsl.get("transformations", [])
    
    for step in transformations:
        # Resolve target column for preview UI matching if it was renamed
        original_col = step.get("column")
        if original_col and original_col in column_mapping:
            step = dict(step)  # copy to avoid mutating original DSL
            step["column"] = column_mapping[original_col]
            
        action = step.get("action", "unknown")
        column = step.get("column")
        new_name = step.get("new_name")
        prefix = step.get("prefix")
        
        df_before = df_current.copy()
        
        # Execute just this single step
        single_step_dsl = {"transformations": [step]}
        df_current, log, _ = execute_dsl(df_current, single_step_dsl, column_mapping)
        
        preview_samples = []
        
        # Determine the columns to compare
        if action == "normalize_columns":
            # Compare column names instead of row values
            for old_col, new_col in zip(df_before.columns, df_current.columns):
                if old_col != new_col:
                    preview_samples.append({"before": old_col, "after": new_col})
                    if len(preview_samples) >= 5:
                        break
        elif action == "rename_column" and column and new_name:
            if column in df_before.columns and new_name in df_current.columns:
                preview_samples.append({"before": column, "after": new_name})
        elif action == "flatten_object" and column and prefix:
            if column in df_before.columns:
                # Show an example of the dictionary expanding
                sample_val = df_before[column].dropna().head(1)
                if not sample_val.empty:
                    preview_samples.append({"before": str(sample_val.iloc[0]), "after": f"Flattened into {prefix}* columns"})
        elif action == "drop_column" and column:
            preview_samples.append({"before": column, "after": "Dropped"})
        elif column and column in df_before.columns and column in df_current.columns:
            # Row value comparison for modifications (cast, fill, regex, etc.)
            # We align by index temporarily just to find differences
            try:
                # Compare head matching indices
                min_len = min(len(df_before), len(df_current))
                b_col = df_before[column].head(min_len).astype(str)
                a_col = df_current[column].head(min_len).astype(str)
                
                mask = b_col != a_col
                changed_b = b_col[mask].head(5).tolist()
                changed_a = a_col[mask].head(5).tolist()
                
                for b, a in zip(changed_b, changed_a):
                    preview_samples.append({"before": b, "after": a})
            except Exception:
                pass
                
        previews.append({
            "action": action,
            "column": column,
            "samples": preview_samples,
            "confidence": step.get("confidence", 100)
        })

    return previews, df_current

def _normalized_name(col) -> str:
    """Same rule as the DSL's normalize_columns, to follow a column through a rename."""
    n = re.sub(r"[^a-z0-9_]", "_", str(col).strip().lower())
    return re.sub(r"_+", "_", n).strip("_")


def _column_lineage(before_cols, after_cols, dsl: dict) -> dict:
    """Map each column of the source frame to its name in the result (None if dropped)."""
    renames = {}
    for step in dsl.get("transformations", []):
        if step.get("action") == "rename_column" and step.get("column") and step.get("new_name"):
            renames[step["column"]] = step["new_name"]
    after = set(after_cols)
    lineage = {}
    for col in before_cols:
        candidates = [col, _normalized_name(col)]
        candidates += [renames[c] for c in candidates if c in renames]
        lineage[col] = next((c for c in candidates if c in after), None)
    return lineage


def generate_impact_summary(df_before: pd.DataFrame, df_after: pd.DataFrame, dsl: dict) -> dict:
    """
    Computes the Migration Impact Report including Data Quality metrics.
    Missing values are compared per surviving column, so cells that disappear
    with a dropped column are not counted as "filled".
    """
    profile_before = profile_dataframe(df_before)
    profile_after = profile_dataframe(df_after)
    missing_b = {c: v.get("missing_count", 0) for c, v in profile_before.get("columns", {}).items()}
    missing_a = {c: v.get("missing_count", 0) for c, v in profile_after.get("columns", {}).items()}

    score_before = profile_before.get("data_quality_score", 0)
    score_after = profile_after.get("data_quality_score", 0)

    lineage = _column_lineage(df_before.columns, df_after.columns, dsl)
    kept = {b: a for b, a in lineage.items() if a is not None}
    dropped = [b for b, a in lineage.items() if a is None]
    added = [c for c in df_after.columns if c not in set(kept.values())]

    missing_filled = sum(max(0, missing_b.get(b, 0) - missing_a.get(a, 0)) for b, a in kept.items())
    set_to_null = sum(max(0, missing_a.get(a, 0) - missing_b.get(b, 0)) for b, a in kept.items())

    currency_cols = {step.get("column") for step in dsl.get("transformations", []) if step.get("action") == "parse_currency"}
    datetime_standardized = currency_parsed = fields_normalized = 0
    for b, a in kept.items():
        before, after = df_before[b], df_after[a]
        if pd.api.types.is_datetime64_any_dtype(after) and not pd.api.types.is_datetime64_any_dtype(before):
            datetime_standardized += int(after.notna().sum())
        elif a in currency_cols or b in currency_cols:
            currency_parsed += int(after.notna().sum())
        elif after.dtype == object and before.dtype == object and len(before) == len(after):
            both = before.notna().values & after.notna().values
            fields_normalized += int((before.astype(str).values != after.astype(str).values)[both].sum())

    row_delta = len(df_before) - len(df_after)

    return {
        "rows_before": len(df_before),
        "rows_after": len(df_after),
        "duplicates_removed": max(row_delta, 0),
        "columns_renamed": sum(1 for b, a in kept.items() if b != a),
        "columns_dropped": len(dropped),
        "columns_added": len(added),
        "missing_filled": missing_filled,
        "datetime_standardized": datetime_standardized,
        "currency_parsed": currency_parsed,
        "fields_normalized": fields_normalized,
        "missing_before": sum(missing_b.values()),
        "missing_after": sum(missing_a.values()),
        "missing_in_dropped_columns": sum(missing_b.get(b, 0) for b in dropped),
        "parsing_induced_nulls": set_to_null,
        "quality_score_before": score_before,
        "quality_score_after": score_after,
        "improvement_pct": round(score_after - score_before, 2)
    }

def generate_risk_assessment(dsl: dict) -> dict:
    """
    Classifies transformation actions by confidence scores into risk tiers.
    """
    high_risk = []
    medium_risk = []
    low_risk = []
    
    transformations = dsl.get("transformations", [])
    total_confidence = 0
    
    for t in transformations:
        action = t.get("action", "unknown")
        conf = t.get("confidence", 100)
        total_confidence += conf
        
        if action == "fill_missing":   # writes values that were never in the source
            high_risk.append(action)
        elif conf >= 90:
            low_risk.append(action)
        elif conf >= 70:
            medium_risk.append(action)
        else:
            high_risk.append(action)
            
    avg_conf = round(total_confidence / len(transformations)) if transformations else 100
    
    return {
        "overall_confidence": avg_conf,
        "low_risk": list(set(low_risk)),
        "medium_risk": list(set(medium_risk)),
        "high_risk": list(set(high_risk))
    }
