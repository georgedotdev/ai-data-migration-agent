"""
Transformation DSL Engine

JSON-driven transformation executor. The AI Brain outputs a strict
JSON Transformation DSL, and this engine executes it using a registry
of deterministic, pre-coded action handlers.

The AI NEVER generates or executes arbitrary Python/Pandas code.
It reasons and selects actions. This engine acts.

Supported actions (V2 launch set):
    - normalize_columns: Lowercase + underscore all column names
    - fill_missing:      Fill nulls in a specific column with a value
    - remove_duplicates: Deduplicate on column or full-row
    - cast_type:         Cast column to int64, float64, str, datetime
    - rename_column:     Rename a column
    - flatten_object:    Flatten nested dict column into prefixed flat columns
    - drop_column:       Remove a column

DSL Contract (input format):
    {
        "transformations": [
            { "action": "normalize_columns" },
            { "action": "fill_missing", "column": "email", "value": "UNKNOWN" },
            { "action": "remove_duplicates", "column": "customer_id" },
            { "action": "cast_type", "column": "revenue", "target_type": "float64" },
            { "action": "rename_column", "column": "customername", "new_name": "customer_name" },
            { "action": "flatten_object", "column": "address", "prefix": "address_" },
            { "action": "drop_column", "column": "internal_notes" }
        ]
    }

Usage:
    from etl.dsl_engine import execute_dsl

    dsl = {"transformations": [{"action": "normalize_columns"}]}
    df_out, log = execute_dsl(df, dsl)
"""

import re
import pandas as pd


# ─────────────────────────────────────────────
# Action Handlers
# ─────────────────────────────────────────────
# Each handler receives (df, step_dict) and returns (df, result_dict).
# Handlers must NEVER modify df in place — always return a new/copied df.

def _action_normalize_columns(df: pd.DataFrame, step: dict):
    """Lowercase all column names and replace spaces/special chars with underscores."""

    original_columns = list(df.columns)
    new_columns = []

    for col in df.columns:
        normalized = col.strip().lower()
        normalized = re.sub(r'[^a-z0-9_]', '_', normalized)
        normalized = re.sub(r'_+', '_', normalized)  # collapse multiple underscores
        normalized = normalized.strip('_')
        new_columns.append(normalized)

    df = df.copy()
    df.columns = new_columns

    renamed = {
        orig: new for orig, new in zip(original_columns, new_columns)
        if orig != new
    }

    return df, {
        "action": "normalize_columns",
        "status": "success",
        "details": {
            "renamed_count": len(renamed),
            "renamed": renamed
        }
    }


def _action_fill_missing(df: pd.DataFrame, step: dict):
    """Fill nulls in a specific column with a specific value or strategy."""

    column = step.get("column")
    strategy = step.get("strategy", "constant")
    value = step.get("value")

    if column is None:
        return df, {
            "action": "fill_missing",
            "status": "error",
            "details": {"error": "Missing required parameter: 'column'"}
        }

    if column not in df.columns:
        return df, {
            "action": "fill_missing",
            "status": "error",
            "details": {"error": f"Column '{column}' not found in DataFrame"}
        }

    df = df.copy()
    null_count_before = int(df[column].isna().sum())
    
    try:
        if strategy == "constant":
            if value is None:
                return df, {"action": "fill_missing", "status": "error", "details": {"error": "Missing 'value' for constant strategy"}}
            df[column] = df[column].fillna(value)
        elif strategy == "mean":
            num_col = pd.to_numeric(df[column], errors='coerce')
            df[column] = df[column].fillna(num_col.mean())
        elif strategy == "median":
            num_col = pd.to_numeric(df[column], errors='coerce')
            df[column] = df[column].fillna(num_col.median())
        elif strategy == "mode":
            mode_val = df[column].mode()
            if not mode_val.empty:
                df[column] = df[column].fillna(mode_val[0])
        elif strategy == "forward_fill":
            df[column] = df[column].ffill()
        elif strategy == "backward_fill":
            df[column] = df[column].bfill()
        else:
            return df, {"action": "fill_missing", "status": "error", "details": {"error": f"Unknown strategy: {strategy}"}}
    except Exception as e:
        return df, {"action": "fill_missing", "status": "error", "details": {"error": str(e)}}

    null_count_after = int(df[column].isna().sum())

    return df, {
        "action": "fill_missing",
        "status": "success",
        "details": {
            "column": column,
            "strategy": strategy,
            "nulls_filled": null_count_before - null_count_after
        }
    }


def _action_remove_duplicates(df: pd.DataFrame, step: dict):
    """Deduplicate on a specific column, or full-row if no column specified."""

    column = step.get("column")

    df = df.copy()
    rows_before = len(df)

    if column:
        if column not in df.columns:
            return df, {
                "action": "remove_duplicates",
                "status": "error",
                "details": {"error": f"Column '{column}' not found in DataFrame"}
            }
        df = df.drop_duplicates(subset=[column], keep="first")
    else:
        df = df.drop_duplicates(keep="first")

    df = df.reset_index(drop=True)
    rows_after = len(df)

    return df, {
        "action": "remove_duplicates",
        "status": "success",
        "details": {
            "column": column or "all_columns",
            "rows_before": rows_before,
            "rows_after": rows_after,
            "rows_removed": rows_before - rows_after
        }
    }


def _action_cast_type(df: pd.DataFrame, step: dict):
    """Cast a column to a target type (int64, float64, str, datetime)."""

    column = step.get("column")
    target_type = step.get("target_type")

    VALID_TYPES = {"int64", "float64", "str", "string", "datetime", "bool"}

    if column is None:
        return df, {
            "action": "cast_type",
            "status": "error",
            "details": {"error": "Missing required parameter: 'column'"}
        }

    if target_type is None:
        return df, {
            "action": "cast_type",
            "status": "error",
            "details": {"error": "Missing required parameter: 'target_type'"}
        }

    if target_type not in VALID_TYPES:
        return df, {
            "action": "cast_type",
            "status": "error",
            "details": {"error": f"Invalid target_type '{target_type}'"}
        }

    if column not in df.columns:
        return df, {
            "action": "cast_type",
            "status": "error",
            "details": {"error": f"Column '{column}' not found in DataFrame"}
        }

    df = df.copy()
    original_dtype = str(df[column].dtype)

    try:
        if target_type in ("int64", "float64"):
            df[column] = pd.to_numeric(df[column], errors="coerce").astype(target_type)
        elif target_type == "datetime":
            df[column] = pd.to_datetime(df[column], errors="coerce")
        elif target_type in ("str", "string"):
            df[column] = df[column].astype(str)
        elif target_type == "bool":
            df[column] = df[column].astype(bool)
        elif target_type == "category":
            df[column] = df[column].astype('category')
        else:
            df[column] = pd.to_numeric(df[column], errors="coerce").astype(target_type)
    except Exception as e:
        return df, {
            "action": "cast_type",
            "status": "error",
            "details": {
                "column": column,
                "target_type": target_type,
                "error": str(e)
            }
        }

    return df, {
        "action": "cast_type",
        "status": "success",
        "details": {
            "column": column,
            "original_dtype": original_dtype,
            "target_dtype": target_type,
            "new_dtype": str(df[column].dtype)
        }
    }


def _action_rename_column(df: pd.DataFrame, step: dict):
    """Rename a single column."""

    column = step.get("column")
    new_name = step.get("new_name")

    if column is None:
        return df, {
            "action": "rename_column",
            "status": "error",
            "details": {"error": "Missing required parameter: 'column'"}
        }

    if new_name is None:
        return df, {
            "action": "rename_column",
            "status": "error",
            "details": {"error": "Missing required parameter: 'new_name'"}
        }

    if column not in df.columns:
        return df, {
            "action": "rename_column",
            "status": "error",
            "details": {"error": f"Column '{column}' not found in DataFrame"}
        }

    df = df.copy()
    df = df.rename(columns={column: new_name})

    return df, {
        "action": "rename_column",
        "status": "success",
        "details": {
            "original_name": column,
            "new_name": new_name
        }
    }


def _action_flatten_object(df: pd.DataFrame, step: dict):
    """Flatten a column containing dicts into multiple prefixed columns."""

    column = step.get("column")
    prefix = step.get("prefix", "")

    if column is None:
        return df, {
            "action": "flatten_object",
            "status": "error",
            "details": {"error": "Missing required parameter: 'column'"}
        }

    if column not in df.columns:
        return df, {
            "action": "flatten_object",
            "status": "error",
            "details": {"error": f"Column '{column}' not found in DataFrame"}
        }

    df = df.copy()

    # Check that the column actually contains dicts
    sample = df[column].dropna().head(10)
    dict_count = sum(1 for v in sample if isinstance(v, dict))

    if dict_count == 0:
        return df, {
            "action": "flatten_object",
            "status": "error",
            "details": {
                "error": f"Column '{column}' does not contain nested objects"
            }
        }

    # Normalize dicts (handle non-dict values as empty dicts)
    normalized = df[column].apply(
        lambda x: x if isinstance(x, dict) else {}
    )
    flattened = pd.json_normalize(normalized)

    # Apply prefix to new column names
    if prefix:
        flattened.columns = [f"{prefix}{col}" for col in flattened.columns]

    # Align index
    flattened.index = df.index

    # Drop original column and insert new columns
    insert_pos = df.columns.get_loc(column)
    df = df.drop(columns=[column])

    for i, col_name in enumerate(flattened.columns):
        df.insert(insert_pos + i, col_name, flattened[col_name])

    return df, {
        "action": "flatten_object",
        "status": "success",
        "details": {
            "original_column": column,
            "prefix": prefix,
            "new_columns": list(flattened.columns),
            "new_column_count": len(flattened.columns)
        }
    }


def _action_drop_column(df: pd.DataFrame, step: dict):
    """Drop a single column."""

    column = step.get("column")

    if column is None:
        return df, {
            "action": "drop_column",
            "status": "error",
            "details": {"error": "Missing required parameter: 'column'"}
        }

    if column not in df.columns:
        return df, {
            "action": "drop_column",
            "status": "error",
            "details": {"error": f"Column '{column}' not found in DataFrame"}
        }

    df = df.copy()
    df = df.drop(columns=[column])

    return df, {
        "action": "drop_column",
        "status": "success",
        "details": {
            "dropped_column": column
        }
    }


# ─────────────────────────────────────────────
# Action Registry
# ─────────────────────────────────────────────

from .dsl_handlers_extended import EXTENDED_HANDLERS

ACTION_REGISTRY = {
    "normalize_columns": _action_normalize_columns,
    "fill_missing": _action_fill_missing,
    "remove_duplicates": _action_remove_duplicates,
    "cast_type": _action_cast_type,
    "rename_column": _action_rename_column,
    "flatten_object": _action_flatten_object,
    "drop_column": _action_drop_column,
    **EXTENDED_HANDLERS
}


def list_actions():
    """Return list of available DSL actions."""
    return sorted(ACTION_REGISTRY.keys())


# ─────────────────────────────────────────────
# DSL Executor
# ─────────────────────────────────────────────

def execute_dsl(
    df: pd.DataFrame,
    dsl: dict,
    column_mapping: dict = None
) -> tuple:
    """
    Execute a JSON DSL transformation plan.

    Args:
        df: Input DataFrame.
        dsl: Dict with a "transformations" key containing a list of steps.
             Each step has an "action" key and action-specific parameters.
        column_mapping: Optional dict to track and resolve renamed columns across execution chunks.

    Returns:
        tuple: (transformed_df, execution_log)
            - transformed_df: The DataFrame after all transformations
            - execution_log: List of result dicts from each step

    Raises:
        ValueError: If the DSL is malformed (missing "transformations" key)
    """

    if not isinstance(dsl, dict):
        raise ValueError(
            f"DSL must be a dict, got {type(dsl).__name__}"
        )

    steps = dsl.get("transformations")

    if steps is None:
        raise ValueError(
            "DSL must contain a 'transformations' key"
        )

    if not isinstance(steps, list):
        raise ValueError(
            f"'transformations' must be a list, got {type(steps).__name__}"
        )

    log = []
    if column_mapping is None:
        column_mapping = {}

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            log.append({
                "step_index": i,
                "action": "unknown",
                "status": "error",
                "details": {"error": f"Step must be a dict, got {type(step).__name__}"}
            })
            continue

        action = step.get("action")

        if action is None:
            log.append({
                "step_index": i,
                "action": "unknown",
                "status": "error",
                "details": {"error": "Step missing required 'action' key"}
            })
            continue

        handler = ACTION_REGISTRY.get(action)

        if handler is None:
            log.append({
                "step_index": i,
                "action": action,
                "status": "error",
                "details": {
                    "error": f"Unknown action '{action}'. "
                             f"Available: {list_actions()}"
                }
            })
            continue

        # Target Resolution (Phase 2 & 3)
        resolved = False
        original_col = step.get("column")
        if "column" in step and step["column"] in column_mapping:
            step["column"] = column_mapping[step["column"]]
            resolved = True
        
        if "columns" in step and isinstance(step["columns"], list):
            new_cols = []
            for c in step["columns"]:
                if c in column_mapping:
                    new_cols.append(column_mapping[c])
                    resolved = True
                else:
                    new_cols.append(c)
            step["columns"] = new_cols

        # Target Validation
        # If the step defines a column, verify it exists.
        # Note: some actions create columns (e.g., create_column), so we skip validation for them.
        actions_creating_columns = {"create_column", "generate_surrogate_key", "rename_column"}
        target_col = step.get("column")
        if target_col and action not in actions_creating_columns:
            if target_col not in df.columns:
                msg = f"Target column '{target_col}' does not exist"
                if resolved:
                    msg += f" (resolved from '{original_col}')"
                log.append({
                    "step_index": i,
                    "action": action,
                    "status": "skipped",
                    "details": {"reason": msg}
                })
                continue

        try:
            df, result = handler(df, step)
            result["step_index"] = i
            if "action" not in result:
                result["action"] = action
            if resolved:
                if "details" not in result:
                    result["details"] = {}
                result["details"]["resolved_from"] = original_col
            log.append(result)
            
            # Update column mappings if step was successful
            if result.get("status") == "success":
                details = result.get("details", {})
                if action == "normalize_columns" and "renamed" in details:
                    for old, new in details["renamed"].items():
                        for k, v in column_mapping.items():
                            if v == old:
                                column_mapping[k] = new
                        column_mapping[old] = new
                elif action == "rename_column" and "original_name" in details and "new_name" in details:
                    old = details["original_name"]
                    new = details["new_name"]
                    for k, v in column_mapping.items():
                        if v == old:
                            column_mapping[k] = new
                    column_mapping[old] = new

        except Exception as e:
            log.append({
                "step_index": i,
                "action": action,
                "status": "error",
                "details": {"error": f"Unexpected error: {str(e)}"}
            })

    return df, log


# ─────────────────────────────────────────────
# DSL Validation
# ─────────────────────────────────────────────

def validate_dsl(dsl: dict) -> tuple:
    """
    Validate a DSL plan without executing it.

    Returns:
        tuple: (is_valid, errors)
            - is_valid: True if the DSL is structurally valid
            - errors: List of error strings (empty if valid)
    """

    errors = []

    if not isinstance(dsl, dict):
        return False, [f"DSL must be a dict, got {type(dsl).__name__}"]

    steps = dsl.get("transformations")

    if steps is None:
        return False, ["DSL must contain a 'transformations' key"]

    if not isinstance(steps, list):
        return False, [f"'transformations' must be a list, got {type(steps).__name__}"]

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"Step {i}: must be a dict")
            continue

        action = step.get("action")
        if action is None:
            errors.append(f"Step {i}: missing 'action' key")
            continue

        if action not in ACTION_REGISTRY:
            errors.append(
                f"Step {i}: unknown action '{action}'. "
                f"Available: {list_actions()}"
            )

    return len(errors) == 0, errors
