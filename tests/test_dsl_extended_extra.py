import pytest
import pandas as pd
import numpy as np
from etl.dsl_engine import execute_dsl

# --- More specific tests for 100+ target ---
def test_extract_year_edge_cases():
    df = pd.DataFrame({"dt": ["2020-05-10", "invalid", np.nan]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "extract_year", "column": "dt"}]})
    assert res_df["dt_year"].iloc[0] == 2020
    assert pd.isna(res_df["dt_year"].iloc[1])

def test_extract_month_edge_cases():
    df = pd.DataFrame({"dt": ["2020-05-10", "invalid", np.nan]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "extract_month", "column": "dt"}]})
    assert res_df["dt_month"].iloc[0] == 5
    assert pd.isna(res_df["dt_month"].iloc[1])

def test_extract_day_edge_cases():
    df = pd.DataFrame({"dt": ["2020-05-10", "invalid", np.nan]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "extract_day", "column": "dt"}]})
    assert res_df["dt_day"].iloc[0] == 10
    assert pd.isna(res_df["dt_day"].iloc[1])

def test_parse_currency_commas():
    df = pd.DataFrame({"rev": ["$1,000,000.50", "1,000"]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "parse_currency", "column": "rev"}]})
    assert res_df["rev"].iloc[0] == 1000000.50
    assert res_df["rev"].iloc[1] == 1000.0

def test_parse_percentage_commas():
    df = pd.DataFrame({"pct": ["99.9%", "100 %"]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "parse_percentage", "column": "pct"}]})
    assert res_df["pct"].iloc[0] == pytest.approx(0.999)
    assert res_df["pct"].iloc[1] == pytest.approx(1.0)

def test_parse_rating_decimals():
    df = pd.DataFrame({"rating": ["4.5 stars", "5.0/5"]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "parse_rating", "column": "rating"}]})
    assert res_df["rating"].iloc[0] == 4.5
    assert res_df["rating"].iloc[1] == 5.0

def test_split_regex():
    df = pd.DataFrame({"col": ["A-B", "C_D"]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "split_column", "column": "col", "regex": r"[-_]"}]})
    assert res_df["col_1"].iloc[0] == "A"
    assert res_df["col_2"].iloc[1] == "D"

def test_serialize_json_lists():
    df = pd.DataFrame({"col": [[1, 2], [3]]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "serialize_json", "column": "col"}]})
    assert res_df["col"].iloc[0] == "[1, 2]"

def test_merge_columns_custom_sep():
    df = pd.DataFrame({"a": ["1"], "b": ["2"]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "merge_columns", "columns": ["a", "b"], "new_name": "c", "separator": "-"}]})
    assert res_df["c"].iloc[0] == "1-2"

def test_create_column_numeric():
    df = pd.DataFrame({"a": [1, 2]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "create_column", "new_name": "b", "value": 0}]})
    assert res_df["b"].iloc[0] == 0

def test_validate_country_code():
    df = pd.DataFrame({"cc": ["US", "USA", "U", "united states"]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "validate_country_code", "column": "cc"}]})
    assert res_df["cc"].iloc[0] == "US"
    assert res_df["cc"].iloc[1] == "USA"
    assert pd.isna(res_df["cc"].iloc[2])

def test_detect_outliers_adds_column():
    df = pd.DataFrame({"val": [10, 10, 10, 1000]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "detect_outliers", "column": "val"}]})
    assert "val_is_outlier" in res_df.columns
    assert res_df["val_is_outlier"].iloc[3] == True

def test_clip_outliers_lower_bound():
    df = pd.DataFrame({"val": [10, 10, 10, -1000]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "clip_outliers", "column": "val"}]})
    assert res_df["val"].iloc[3] > -1000

def test_surrogate_key_generation():
    df = pd.DataFrame({"a": [1, 2, 3]})
    res_df, log, quarantine = execute_dsl(df, {"transformations": [{"action": "generate_surrogate_key", "column": "id"}]})
    assert len(res_df["id"].unique()) == 3


def test_replace_with_null_accepts_llm_value_field():
    """LLMs send sentinels as `value` (string or list); both must work, as must `values`."""
    df = pd.DataFrame({"a": ["1", "N/A", "3"], "b": ["x", "UNKNOWN", "y"], "c": ["?", "ok", "-"]})
    res_df, log, _ = execute_dsl(df, {"transformations": [
        {"action": "replace_with_null", "column": "a", "value": ["N/A"]},
        {"action": "replace_with_null", "column": "b", "value": "UNKNOWN"},
        {"action": "replace_with_null", "column": "c", "values": ["?", "-"]},
    ]})
    assert [e["status"] for e in log] == ["success"] * 3
    assert res_df["a"].isna().tolist() == [False, True, False]
    assert res_df["b"].isna().tolist() == [False, True, False]
    assert res_df["c"].isna().tolist() == [True, False, True]


def test_cast_int64_with_missing_values_uses_nullable_int():
    df = pd.DataFrame({"age": ["30", None, "41"]})
    res_df, log, _ = execute_dsl(df, {"transformations": [{"action": "cast_type", "column": "age", "target_type": "int64"}]})
    assert log[0]["status"] == "success"
    assert str(res_df["age"].dtype) == "Int64"
    assert res_df["age"].tolist()[0] == 30 and pd.isna(res_df["age"].tolist()[1])


def test_llm_schema_allows_values_list():
    from ai_brain import DSLStep
    step = DSLStep(action="replace_with_null", column="status", values=["UNKNOWN", "N/A"])
    assert step.values == ["UNKNOWN", "N/A"]
