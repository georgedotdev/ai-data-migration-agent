import os

import pandas as pd
import pytest

from etl.cleaning import clean_for_migration

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _raw(**cols):
    return pd.DataFrame(cols, dtype=str)


def test_row_accounting_balances_on_demo_datasets():
    for name in ("dirty_employees.csv", "dirty_orders.csv"):
        raw = pd.read_csv(os.path.join(DATA, name), dtype=str, keep_default_na=False)
        r = clean_for_migration(raw)
        s = r.stats
        assert s["source_rows"] == s["loaded_rows"] + s["exact_duplicates_removed"] + s["quarantined_rows"]
        assert r.df[r.primary_key].is_unique
        assert r.df[r.primary_key].notna().all()


def test_currency_k_suffix_and_unparseable_values():
    r = clean_for_migration(_raw(emp_id=["1", "2", "3", "4", "5"],
                                 salary=["$1,200", "55k", "USD 72,500", "N/A", "abc"]))
    assert list(r.df["salary"][:3]) == [1200.0, 55000.0, 72500.0]
    assert r.df["salary"][3:].isna().all()
    assert r.semantics["salary"] == "money"


def test_negative_money_and_out_of_range_age_become_null():
    r = clean_for_migration(_raw(emp_id=["1", "2", "3", "4"], salary=["100", "-5", "200", "300"],
                                 age=["30", "999", "-4", "45"]))
    assert pd.isna(r.df["salary"][1])
    assert r.df["age"].isna().sum() == 2


def test_category_variants_typos_and_acronyms_are_merged():
    values = ["Engineering"] * 6 + ["engineering", "ENGINEERING", "Enginering"] + ["Sales"] * 6 + ["SALES"]
    r = clean_for_migration(_raw(emp_id=[str(i) for i in range(len(values))], department=values))
    assert set(r.df["department"]) == {"Engineering", "Sales"}

    pay = ["Cash on Delivery"] * 9 + ["COD"] + ["PayPal"] * 9 + ["Pay Pal"]
    r = clean_for_migration(_raw(order_id=[str(i) for i in range(len(pay))], payment=pay))
    assert set(r.df["payment"]) == {"Cash on Delivery", "PayPal"}


def test_booleans_dates_percentages_and_emails():
    r = clean_for_migration(_raw(
        emp_id=["1", "2", "3", "4"],
        remote=["Yes", "N", "TRUE", "0"],
        joined=["2021-03-15", "3/16/2021", "2021/03/17", "Mar 18 2021"],
        discount=["15%", "15 %", "0.15", "15"],
        email=["a.b@x.com", "a.b@", "n/a", "C@Y.ORG"],
    ))
    assert list(r.df["remote"]) == [True, False, True, False]
    assert list(r.df["joined"].dt.day) == [15, 16, 17, 18]
    assert all(abs(v - 0.15) < 1e-9 for v in r.df["discount"])
    assert r.df["email"].tolist()[0] == "a.b@x.com" and r.df["email"].tolist()[3] == "c@y.org"
    assert r.df["email"][1:3].isna().all()


def test_missing_and_conflicting_keys_are_quarantined_not_dropped():
    ids = [str(i) for i in range(1, 21)]
    names = [f"N{i}" for i in range(1, 21)]
    # one row without key, one exact duplicate of id 2, one conflicting re-entry of id 3
    r = clean_for_migration(_raw(emp_id=ids + ["", "2", "3"], name=names + ["X", "N2", "N3-changed"]))
    assert r.stats == {**r.stats, "source_rows": 23, "loaded_rows": 20,
                       "exact_duplicates_removed": 1, "quarantined_rows": 2}
    assert set(r.quarantine["reason"].str.split(" ").str[0]) == {"missing", "duplicate"}


def test_missing_values_are_not_imputed():
    r = clean_for_migration(_raw(emp_id=["1", "2", "3"], salary=["100", "", "300"]))
    assert pd.isna(r.df["salary"][1])


@pytest.mark.parametrize("bad", ["drop table x", "a-b", "1abc", "x" * 49, ""])
def test_safe_ident_rejects_unsafe_names(bad):
    from etl.sql_schema import safe_ident
    with pytest.raises(ValueError):
        safe_ident(bad)


def test_columns_without_any_value_are_dropped():
    r = clean_for_migration(_raw(order_id=["1", "2", "3"], amount=["5", "6", "7"],
                                 unnamed_8=["", "", ""], notes=["N/A", "", "ok"]))
    assert "unnamed_8" not in r.df.columns
    assert "notes" in r.df.columns
    assert any(e["action"] == "drop_empty_column" and e["column"] == "unnamed_8" for e in r.log)
