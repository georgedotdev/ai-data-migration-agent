import os

import pandas as pd

from etl.cleaning import clean_for_migration
from etl.mysql_loader import checksum_rows, prepare_rows
from etl.sql_schema import design_normalized, design_table

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _employees():
    raw = pd.read_csv(os.path.join(DATA, "dirty_employees.csv"), dtype=str, keep_default_na=False)
    return clean_for_migration(raw)


def test_flat_ddl_has_types_keys_and_checks():
    r = _employees()
    td = design_table(r.df, "employees", r.semantics, r.primary_key, ["join_date"])
    ddl = td.create_sql()
    assert "PRIMARY KEY (`employee_id`)" in ddl
    assert "`annual_salary` DECIMAL(12,2)" in ddl
    assert "CHECK (`annual_salary` >= 0)" in ddl
    assert "CHECK (`age` BETWEEN 16 AND 100)" in ddl
    assert "`join_date` DATE" in ddl
    assert "`is_remote` BOOLEAN NOT NULL" in ddl
    assert "INDEX `idx_join_date`" in ddl
    assert "INDEX" not in td.create_sql(include_indexes=False)


def test_normalized_design_has_lookup_and_foreign_key():
    r = _employees()
    lookup_def, lookup_df, main_def, main_df = design_normalized(
        r.df, "employees", r.semantics, r.primary_key, "department", "departments")
    assert list(lookup_df.columns) == ["id", "department"]
    assert lookup_df["department"].is_unique
    assert "department" not in main_df.columns and "department_id" in main_df.columns
    assert "UNIQUE KEY `uq_department`" in lookup_def.create_sql()
    ddl = main_def.create_sql("employees__stg", ref_map={"departments": "departments__stg"})
    assert "FOREIGN KEY (`department_id`) REFERENCES `departments__stg` (`id`)" in ddl
    # every FK value points at an existing lookup id
    assert set(main_df["department_id"].dropna()) <= set(lookup_df["id"])


def test_checksum_is_order_independent_and_type_canonical():
    r = _employees()
    td = design_table(r.df, "employees", r.semantics, r.primary_key)
    rows = prepare_rows(td, r.df)
    assert checksum_rows(td, rows) == checksum_rows(td, list(reversed(rows)))
    # A value read back from MySQL as Decimal/int must hash like the pandas float/bool
    from decimal import Decimal
    idx = [c.name for c in td.columns].index("annual_salary")
    first = list(rows[0])
    if first[idx] is not None:
        first[idx] = Decimal(str(first[idx]))
    assert checksum_rows(td, [tuple(first)] + rows[1:]) == checksum_rows(td, rows)


def test_functional_dependency_moves_dependent_column_into_lookup():
    raw = pd.read_csv(os.path.join(DATA, "dirty_orders.csv"), dtype=str, keep_default_na=False)
    r = clean_for_migration(raw)
    lookup_def, lookup_df, main_def, main_df = design_normalized(
        r.df, "orders", r.semantics, r.primary_key, "product", "products")
    assert main_def.dependents == ["category"]          # product -> category holds in the data
    assert list(lookup_df.columns) == ["id", "product", "category"]
    assert "category" not in main_df.columns and "product" not in main_df.columns
    # lossless: joining back reproduces the original product/category pairs
    rejoined = main_df.merge(lookup_df, left_on="product_id", right_on="id")
    original = r.df.set_index("order_id")[["product", "category"]]
    assert (rejoined.set_index("order_id")[["product", "category"]].sort_index() == original.sort_index()).all().all()
