"""
Transformation Preview and Impact Engine

Generates step-by-step previews of data transformations and computes
the overall migration impact and risk assessment.
"""

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

    transformations = dsl.get("transformations", [])
    
    for step in transformations:
        action = step.get("action", "unknown")
        column = step.get("column")
        new_name = step.get("new_name")
        prefix = step.get("prefix")
        
        df_before = df_current.copy()
        
        # Execute just this single step
        single_step_dsl = {"transformations": [step]}
        df_current, log = execute_dsl(df_current, single_step_dsl)
        
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

def generate_impact_summary(df_before: pd.DataFrame, df_after: pd.DataFrame, dsl: dict) -> dict:
    """
    Computes the Migration Impact Report including Data Quality metrics.
    """
    
    profile_before = profile_dataframe(df_before)
    profile_after = profile_dataframe(df_after)
    
    score_before = profile_before.get("data_quality_score", 0)
    score_after = profile_after.get("data_quality_score", 0)
    
    duplicates_removed = 0
    cols_renamed = 0
    cols_dropped = 0
    cols_added = 0
    
    missing_filled = 0
    datetime_standardized = 0
    currency_parsed = 0
    fields_normalized = 0
    
    transformations = dsl.get("transformations", [])
    for t in transformations:
        action = t.get("action")
        if action == "remove_duplicates":
            duplicates_removed += 1 # Rough count of actions, exact rows is below
        elif action == "rename_column":
            cols_renamed += 1
        elif action == "drop_column":
            cols_dropped += 1
        elif action == "split_column" or action == "flatten_object":
            cols_added += 1
        elif action == "fill_missing":
            missing_filled += 1
        elif action == "parse_datetime":
            datetime_standardized += 1
        elif action == "clean_currency":
            currency_parsed += 1
        elif action == "normalize_columns":
            fields_normalized += 1
            cols_renamed += 1 # count as schema change too
            
    # Extract exact counts for forensics
    missing_before = sum(col.get("missing_count", 0) for col in profile_before.get("columns", {}).values())
    missing_after = sum(col.get("missing_count", 0) for col in profile_after.get("columns", {}).values())
    
    dupes_before = profile_before.get("duplicate_rows", 0)
    dupes_after = profile_after.get("duplicate_rows", 0)

    # Calculate duplicates removed correctly by checking log or row delta
    row_delta = len(df_before) - len(df_after)
    actual_dups_removed = row_delta if row_delta > 0 else 0

    return {
        "rows_before": len(df_before),
        "rows_after": len(df_after),
        "duplicates_removed": actual_dups_removed,
        "columns_renamed": cols_renamed,
        "columns_dropped": cols_dropped,
        "columns_added": cols_added,
        "missing_filled": missing_filled,
        "datetime_standardized": datetime_standardized,
        "currency_parsed": currency_parsed,
        "fields_normalized": fields_normalized,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "dupes_before": dupes_before,
        "dupes_after": dupes_after,
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
        
        if conf >= 90:
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
