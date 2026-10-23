"""The agentic workflow loads through the same schema design and verification as the deterministic migration."""

import pandas as pd
from sqlalchemy import text

from etl.agent_load import infer_semantics, load_and_verify, safe_columns
from etl.dsl_engine import execute_dsl
from etl.endpoints import Endpoint
from etl.preview import generate_impact_summary
from profiling.data_profiler import profile_dataframe


def _cafe():
    return pd.DataFrame({
        "transaction_id": ["TXN_1", "TXN_2", "TXN_3", "TXN_4"],
        "item": ["Coffee", None, "Cake", "Tea"],
        "quantity": pd.array([2, 4, None, 1], dtype="Int64"),
        "price_per_unit": [2.0, 3.0, 3.0, None],
        "total_spent": [4.0, 12.0, None, 1.5],
        "transaction_date": pd.to_datetime(["2023-09-08", "2023-05-16", None, "2023-01-02"]),
    })


def test_infer_semantics_from_typed_data():
    semantics, pk = infer_semantics(_cafe())
    assert pk == "transaction_id"
    assert semantics["quantity"] == "quantity"
    assert semantics["price_per_unit"] == semantics["total_spent"] == "money"
    assert semantics["transaction_date"] == "date"
    assert semantics["item"] == "text"


def test_domain_rule_only_when_every_value_satisfies_it():
    df = _cafe()
    df.loc[0, "total_spent"] = -4.0
    semantics, _ = infer_semantics(df)
    assert semantics["total_spent"] == "float"     # no CHECK (total_spent >= 0) that the data would violate


def test_no_primary_key_when_ids_repeat_or_are_missing():
    df = _cafe()
    df.loc[1, "transaction_id"] = "TXN_1"
    assert infer_semantics(df)[1] is None


def test_safe_columns_makes_valid_identifiers():
    df, renamed = safe_columns(pd.DataFrame(columns=["Price Per Unit", "1st", "ok", "ok "]))
    assert list(df.columns) == ["price_per_unit", "c_1st", "ok", "ok_2"]
    assert ("Price Per Unit", "price_per_unit") in renamed


def test_load_and_verify_builds_constrained_schema(tmp_path):
    src, tgt = str(tmp_path / "src.sqlite"), str(tmp_path / "tgt.sqlite")
    raw = _cafe().astype(str)
    raw.to_sql("cafe_raw", Endpoint("sqlite", {"path": src}).engine(), index=False)
    res = load_and_verify("sqlite", {"db_path": src, "table_name": "cafe_raw"},
                          "sqlite", {"db_path": tgt, "table_name": "cafe"}, len(raw), _cafe(), [])
    assert res["passed"], [c for c in res["checks"] if not c["passed"]]
    assert res["primary_key"] == "transaction_id"
    assert 'PRIMARY KEY ("transaction_id")' in res["ddl"]
    assert "CHECK" in res["ddl"]
    assert any(c["check"].startswith("Database rejects invalid") for c in res["checks"])
    with Endpoint("sqlite", {"path": tgt}).engine().connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM cafe")).scalar() == 4
        assert c.execute(text("SELECT loaded_rows FROM migration_runs")).scalar() == 4


def test_blank_strings_are_reported_and_nulled():
    df = pd.DataFrame({"payment": ["Cash", "", "  ", "ERROR", "Card"]})
    sentinels = profile_dataframe(df)["columns"]["payment"]["suspected_sentinels"]
    assert "" in sentinels and "ERROR" in sentinels
    out, _, _ = execute_dsl(df, {"transformations": [
        {"action": "replace_with_null", "column": "payment", "values": sentinels}]})
    assert out["payment"].isna().sum() == 3


def test_impact_summary_counts_dropped_columns_separately():
    before = pd.DataFrame({"Item": ["Cake", "", "Tea"], "Unnamed: 8": ["", "", ""]})
    dsl = {"transformations": [{"action": "normalize_columns"}, {"action": "drop_column", "column": "unnamed_8"},
                               {"action": "replace_with_null", "column": "item", "values": [""]}]}
    after, _, _ = execute_dsl(before, dsl)
    impact = generate_impact_summary(before, after, dsl)
    assert impact["columns_dropped"] == 1
    assert impact["columns_renamed"] == 1
    assert impact["missing_filled"] == 0
    assert impact["missing_in_dropped_columns"] == 3
