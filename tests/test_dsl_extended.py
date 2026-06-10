import pytest
import pandas as pd
import numpy as np
from etl.dsl_engine import execute_dsl, ACTION_REGISTRY

def test_drop_missing_rows():
    df = pd.DataFrame({"a": [1, 2, np.nan], "b": [np.nan, 2, 3]})
    dsl = {"transformations": [{"action": "drop_missing_rows", "column": "a"}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert len(res_df) == 2
    assert "drop_missing_rows" in log[0]["action"]
    
    dsl_all = {"transformations": [{"action": "drop_missing_rows"}]}
    res_df_all, log_all = execute_dsl(df, dsl_all)
    assert len(res_df_all) == 1

def test_fill_missing_strategies():
    df = pd.DataFrame({"a": [1.0, 3.0, np.nan], "b": ["x", np.nan, "x"]})
    
    # mean
    dsl_mean = {"transformations": [{"action": "fill_missing", "column": "a", "strategy": "mean"}]}
    res_df, log, quarantine = execute_dsl(df, dsl_mean)
    assert res_df["a"].iloc[2] == 2.0
    
    # mode
    dsl_mode = {"transformations": [{"action": "fill_missing", "column": "b", "strategy": "mode"}]}
    res_df, log, quarantine = execute_dsl(df, dsl_mode)
    assert res_df["b"].iloc[1] == "x"

def test_keep_latest_duplicate():
    df = pd.DataFrame({
        "id": [1, 1, 2],
        "ts": ["2023-01-01", "2023-01-02", "2023-01-01"],
        "val": ["A", "B", "C"]
    })
    dsl = {"transformations": [{"action": "keep_latest_duplicate", "column": "id", "timestamp_column": "ts"}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert len(res_df) == 2
    # ID 1 should have val B
    assert res_df.loc[res_df["id"] == 1, "val"].iloc[0] == "B"

def test_parse_currency():
    df = pd.DataFrame({"rev": ["€67.5M", "$120.3M", "£45K", "100", np.nan, "invalid"]})
    dsl = {"transformations": [{"action": "parse_currency", "column": "rev"}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert res_df["rev"].iloc[0] == 67500000.0
    assert res_df["rev"].iloc[1] == 120300000.0
    assert res_df["rev"].iloc[2] == 45000.0
    assert res_df["rev"].iloc[3] == 100.0
    assert pd.isna(res_df["rev"].iloc[4])
    assert pd.isna(res_df["rev"].iloc[5])

def test_parse_height_weight():
    df = pd.DataFrame({
        "height": ["5'7\"", "6'2", "180cm", np.nan],
        "weight": ["159lbs", "72kg", np.nan, "100"]
    })
    dsl_h = {"transformations": [{"action": "parse_height", "column": "height"}]}
    res_df, log, quarantine = execute_dsl(df, dsl_h)
    assert round(res_df["height"].iloc[0], 2) == 170.18 # 5'7
    
    dsl_w = {"transformations": [{"action": "parse_weight", "column": "weight"}]}
    res_df, log, quarantine = execute_dsl(df, dsl_w)
    assert round(res_df["weight"].iloc[0], 2) == 72.12 # 159 lbs -> kg
    assert res_df["weight"].iloc[1] == 72.0

def test_string_cleaning():
    df = pd.DataFrame({"text": [" Hello World! \n ", "HELLO", "test"]})
    dsl = {"transformations": [
        {"action": "trim_whitespace", "column": "text"},
        {"action": "normalize_case", "column": "text"},
        {"action": "strip_special_characters", "column": "text"},
        {"action": "remove_line_breaks", "column": "text"}
    ]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert len(log) == 4
    assert res_df["text"].iloc[0] == "hello world"

def test_split_column():
    df = pd.DataFrame({"name": ["John Doe", "Jane Smith"]})
    dsl = {"transformations": [{"action": "split_column", "column": "name", "delimiter": " "}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert "name_part1" in res_df.columns
    assert res_df["name_part1"].iloc[0] == "John"
    assert res_df["name_part2"].iloc[1] == "Smith"

def test_extract_pattern():
    df = pd.DataFrame({"info": ["Contact: john@example.com", "No email here"]})
    dsl = {"transformations": [{"action": "extract_pattern", "column": "info", "regex": r"[\w\.-]+@[\w\.-]+\.\w+"}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert res_df["info_extracted"].iloc[0] == "john@example.com"
    assert pd.isna(res_df["info_extracted"].iloc[1])

def test_explode_array():
    df = pd.DataFrame({"id": [1, 2], "tags": [["a", "b"], ["c"]]})
    dsl = {"transformations": [{"action": "explode_array", "column": "tags"}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert len(res_df) == 3
    assert list(res_df["tags"]) == ["a", "b", "c"]
    assert list(res_df["id"]) == [1, 1, 2]

def test_data_quality_validators():
    df = pd.DataFrame({
        "email": ["valid@test.com", "invalid-email", np.nan],
        "phone": ["+1234567890", "123", np.nan]
    })
    dsl = {"transformations": [
        {"action": "validate_email", "column": "email"},
        {"action": "validate_phone", "column": "phone"}
    ]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert res_df["email"].iloc[0] == "valid@test.com"
    assert pd.isna(res_df["email"].iloc[1])
    assert res_df["phone"].iloc[0] == "+1234567890"
    assert pd.isna(res_df["phone"].iloc[1])

def test_outliers():
    # 10, 12, 14, 15... 1000 is an outlier
    df = pd.DataFrame({"val": [10, 12, 14, 15, 1000]})
    
    # Clip
    dsl_clip = {"transformations": [{"action": "clip_outliers", "column": "val"}]}
    res_df, log, quarantine = execute_dsl(df, dsl_clip)
    assert res_df["val"].iloc[4] < 1000
    
    # Remove
    dsl_rem = {"transformations": [{"action": "remove_outliers", "column": "val"}]}
    res_df2, _ = execute_dsl(df, dsl_rem)
    assert len(res_df2) == 4

def test_conditional_transform():
    df = pd.DataFrame({"salary": [50000, -1000, 60000]})
    dsl = {"transformations": [{"action": "conditional_transform", "condition": "salary < 0", "operation": "set_null", "column": "salary"}]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert res_df["salary"].iloc[0] == 50000
    assert pd.isna(res_df["salary"].iloc[1])

def test_metadata_tools():
    df = pd.DataFrame({"a": [1, 2]})
    dsl = {"transformations": [
        {"action": "generate_surrogate_key", "column": "pk"},
        {"action": "schema_recommendation"}
    ]}
    res_df, log, quarantine = execute_dsl(df, dsl)
    assert "pk" in res_df.columns
    assert len(res_df["pk"].iloc[0]) == 36 # UUID length
    assert log[1]["status"] == "success"
