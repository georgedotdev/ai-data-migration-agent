"""
Tests for etl/dsl_engine.py

Covers:
- Each action handler individually
- Error handling (missing params, invalid columns, unknown actions)
- Multi-step DSL execution
- DSL validation
- Backward compatibility (V1 transform_data still works)
- flatten_object with MongoDB-style nested dicts
"""

import pytest
import pandas as pd
import numpy as np

from etl.dsl_engine import execute_dsl, validate_dsl, list_actions
from etl.transform import transform_data, transform_data_dsl


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """Standard test DataFrame."""
    return pd.DataFrame({
        "Customer Id": [1, 2, 3, 4, 5],
        "First Name": ["Alice", None, "Charlie", "Diana", None],
        "Last Name": ["Smith", "Jones", "Brown", "Lee", "Kim"],
        "Revenue": [100.5, 200.0, None, 50.0, 300.0],
        "Category": ["A", "B", None, "A", "B"],
    })


@pytest.fixture
def nested_df():
    """DataFrame with MongoDB-style nested objects."""
    return pd.DataFrame({
        "user_id": [1, 2, 3],
        "address": [
            {"street": "123 Main St", "city": "NYC", "zip": "10001"},
            {"street": "456 Oak Ave", "city": "LA", "zip": "90001"},
            {"street": "789 Pine Rd", "city": "CHI", "zip": "60601"},
        ],
        "name": ["Alice", "Bob", "Charlie"],
    })


@pytest.fixture
def dup_df():
    """DataFrame with duplicates."""
    return pd.DataFrame({
        "id": [1, 2, 2, 3, 3, 3],
        "name": ["A", "B", "B", "C", "C", "C"],
        "value": [10, 20, 20, 30, 30, 30],
    })


# ─────────────────────────────────────────────
# Action: normalize_columns
# ─────────────────────────────────────────────

class TestNormalizeColumns:

    def test_lowercases_columns(self, sample_df):
        dsl = {"transformations": [{"action": "normalize_columns"}]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert all(col == col.lower() for col in df_out.columns)
        assert log[0]["status"] == "success"

    def test_replaces_spaces_with_underscores(self, sample_df):
        dsl = {"transformations": [{"action": "normalize_columns"}]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert "customer_id" in df_out.columns
        assert "first_name" in df_out.columns

    def test_does_not_modify_original(self, sample_df):
        original_cols = list(sample_df.columns)
        dsl = {"transformations": [{"action": "normalize_columns"}]}
        execute_dsl(sample_df, dsl)
        assert list(sample_df.columns) == original_cols


# ─────────────────────────────────────────────
# Action: fill_missing
# ─────────────────────────────────────────────

class TestFillMissing:

    def test_fills_string_nulls(self, sample_df):
        dsl = {"transformations": [
            {"action": "fill_missing", "column": "First Name", "value": "UNKNOWN"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert df_out["First Name"].isna().sum() == 0
        assert log[0]["status"] == "success"
        assert log[0]["details"]["nulls_filled"] == 2

    def test_fills_numeric_nulls(self, sample_df):
        dsl = {"transformations": [
            {"action": "fill_missing", "column": "Revenue", "value": 0.0}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert df_out["Revenue"].isna().sum() == 0

    def test_error_missing_column_param(self, sample_df):
        dsl = {"transformations": [
            {"action": "fill_missing", "value": "X"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")

    def test_error_nonexistent_column(self, sample_df):
        dsl = {"transformations": [
            {"action": "fill_missing", "column": "nonexistent", "value": "X"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# Action: remove_duplicates
# ─────────────────────────────────────────────

class TestRemoveDuplicates:

    def test_removes_full_row_duplicates(self, dup_df):
        dsl = {"transformations": [{"action": "remove_duplicates"}]}
        df_out, log, quarantine = execute_dsl(dup_df, dsl)
        assert len(df_out) == 3  # 3 unique rows
        assert log[0]["details"]["rows_removed"] == 3

    def test_removes_column_duplicates(self, dup_df):
        dsl = {"transformations": [
            {"action": "remove_duplicates", "column": "id"}
        ]}
        df_out, log, quarantine = execute_dsl(dup_df, dsl)
        assert len(df_out) == 3  # 3 unique ids
        assert df_out["id"].is_unique

    def test_error_nonexistent_column(self, dup_df):
        dsl = {"transformations": [
            {"action": "remove_duplicates", "column": "nonexistent"}
        ]}
        df_out, log, quarantine = execute_dsl(dup_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# Action: cast_type
# ─────────────────────────────────────────────

class TestCastType:

    def test_cast_to_float64(self, sample_df):
        dsl = {"transformations": [
            {"action": "cast_type", "column": "Customer Id", "target_type": "float64"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert df_out["Customer Id"].dtype == np.float64
        assert log[0]["status"] == "success"

    def test_cast_to_str(self, sample_df):
        dsl = {"transformations": [
            {"action": "cast_type", "column": "Customer Id", "target_type": "str"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        # Newer pandas may return StringDtype instead of object
        assert df_out["Customer Id"].dtype == object or "str" in str(df_out["Customer Id"].dtype).lower()

    def test_error_invalid_type(self, sample_df):
        dsl = {"transformations": [
            {"action": "cast_type", "column": "Customer Id", "target_type": "magic"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")

    def test_error_missing_params(self, sample_df):
        dsl = {"transformations": [
            {"action": "cast_type", "column": "Customer Id"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# Action: rename_column
# ─────────────────────────────────────────────

class TestRenameColumn:

    def test_renames_column(self, sample_df):
        dsl = {"transformations": [
            {"action": "rename_column", "column": "Customer Id", "new_name": "cust_id"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert "cust_id" in df_out.columns
        assert "Customer Id" not in df_out.columns
        assert log[0]["status"] == "success"

    def test_error_missing_new_name(self, sample_df):
        dsl = {"transformations": [
            {"action": "rename_column", "column": "Customer Id"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# Action: flatten_object
# ─────────────────────────────────────────────

class TestFlattenObject:

    def test_flattens_nested_dict(self, nested_df):
        dsl = {"transformations": [
            {"action": "flatten_object", "column": "address", "prefix": "addr_"}
        ]}
        df_out, log, quarantine = execute_dsl(nested_df, dsl)
        assert "address" not in df_out.columns
        assert "addr_street" in df_out.columns
        assert "addr_city" in df_out.columns
        assert "addr_zip" in df_out.columns
        assert log[0]["status"] == "success"
        assert log[0]["details"]["new_column_count"] == 3

    def test_preserves_other_columns(self, nested_df):
        dsl = {"transformations": [
            {"action": "flatten_object", "column": "address", "prefix": "addr_"}
        ]}
        df_out, log, quarantine = execute_dsl(nested_df, dsl)
        assert "user_id" in df_out.columns
        assert "name" in df_out.columns
        assert len(df_out) == 3

    def test_error_non_nested_column(self, sample_df):
        dsl = {"transformations": [
            {"action": "flatten_object", "column": "First Name", "prefix": "fn_"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# Action: drop_column
# ─────────────────────────────────────────────

class TestDropColumn:

    def test_drops_column(self, sample_df):
        dsl = {"transformations": [
            {"action": "drop_column", "column": "Category"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert "Category" not in df_out.columns
        assert len(df_out.columns) == len(sample_df.columns) - 1
        assert log[0]["status"] == "success"

    def test_error_nonexistent_column(self, sample_df):
        dsl = {"transformations": [
            {"action": "drop_column", "column": "nonexistent"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# Multi-Step Execution
# ─────────────────────────────────────────────

class TestMultiStep:

    def test_chained_transformations(self, sample_df):
        dsl = {"transformations": [
            {"action": "normalize_columns"},
            {"action": "fill_missing", "column": "first_name", "value": "UNKNOWN"},
            {"action": "fill_missing", "column": "revenue", "value": 0.0},
            {"action": "drop_column", "column": "category"},
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)

        # All 4 steps should succeed
        assert len(log) == 4
        assert all(entry["status"] == "success" for entry in log)

        # Verify effects
        assert "first_name" in df_out.columns
        assert df_out["first_name"].isna().sum() == 0
        assert df_out["revenue"].isna().sum() == 0
        assert "category" not in df_out.columns

    def test_step_indices_in_log(self, sample_df):
        dsl = {"transformations": [
            {"action": "normalize_columns"},
            {"action": "fill_missing", "column": "first_name", "value": "X"},
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["step_index"] == 0
        assert log[1]["step_index"] == 1


# ─────────────────────────────────────────────
# Error Handling
# ─────────────────────────────────────────────

class TestErrorHandling:

    def test_unknown_action(self, sample_df):
        dsl = {"transformations": [
            {"action": "teleport_data"}
        ]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")
        assert "Unknown action" in log[0]["details"]["error"]

    def test_missing_transformations_key(self, sample_df):
        with pytest.raises(ValueError, match="transformations"):
            execute_dsl(sample_df, {"steps": []})

    def test_invalid_dsl_type(self, sample_df):
        with pytest.raises(ValueError):
            execute_dsl(sample_df, "not a dict")

    def test_non_dict_step_skipped(self, sample_df):
        dsl = {"transformations": ["not_a_dict"]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")

    def test_step_missing_action_key(self, sample_df):
        dsl = {"transformations": [{"column": "x"}]}
        df_out, log, quarantine = execute_dsl(sample_df, dsl)
        assert log[0]["status"] in ("error", "skipped")


# ─────────────────────────────────────────────
# DSL Validation
# ─────────────────────────────────────────────

class TestValidation:

    def test_valid_dsl(self):
        dsl = {"transformations": [
            {"action": "normalize_columns"},
            {"action": "fill_missing", "column": "x", "value": 0},
        ]}
        is_valid, errors = validate_dsl(dsl)
        assert is_valid is True
        assert errors == []

    def test_invalid_missing_key(self):
        is_valid, errors = validate_dsl({"steps": []})
        assert is_valid is False

    def test_invalid_unknown_action(self):
        dsl = {"transformations": [{"action": "magic"}]}
        is_valid, errors = validate_dsl(dsl)
        assert is_valid is False
        assert len(errors) == 1

    def test_list_actions(self):
        actions = list_actions()
        assert "normalize_columns" in actions
        assert "fill_missing" in actions
        assert "flatten_object" in actions
        assert len(actions) >= 7


# ─────────────────────────────────────────────
# Backward Compatibility
# ─────────────────────────────────────────────

class TestBackwardCompat:

    def test_v1_transform_data_still_works(self, sample_df):
        """V1 callers passing a list of strings should work unchanged."""
        result = transform_data(sample_df, ["normalize_columns", "handle_nulls"])
        assert all(col == col.lower() for col in result.columns)
        # V1 handle_nulls fills object-dtype columns; Revenue (float) nulls get filled
        assert result["revenue"].isna().sum() == 0

    def test_v1_transform_data_default(self, sample_df):
        """V1 callers passing None should get all transforms."""
        result = transform_data(sample_df)
        assert all(col == col.lower() for col in result.columns)

    def test_v2_dsl_via_transform_data(self, sample_df):
        """V2 callers can pass a DSL dict to transform_data()."""
        dsl = {"transformations": [
            {"action": "normalize_columns"},
        ]}
        result = transform_data(sample_df, dsl)
        assert "customer_id" in result.columns

    def test_v2_transform_data_dsl(self, sample_df):
        """V2 entry point transform_data_dsl() works."""
        dsl = {"transformations": [
            {"action": "normalize_columns"},
        ]}
        result_df, log = transform_data_dsl(sample_df, dsl)
        assert "customer_id" in result_df.columns
        assert log[0]["status"] == "success"
