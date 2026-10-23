"""
Schema-designed load for the agentic workflow.

The AI plan only cleans the data. Writing the result with pandas.to_sql would
let the driver guess the schema (TEXT, DOUBLE, no keys, no constraints), so the
agent uses the same pipeline as the deterministic migration instead: derive
semantic types from the cleaned, typed DataFrame, design an explicit schema
(types, PRIMARY KEY, NOT NULL, CHECK, index), load it atomically, record the run
and verify it with queries against both systems.
"""

import json
import os
from datetime import datetime

import pandas as pd

from etl import mongo_loader, sql_loader
from etl.cleaning import DOMAIN_RULES, EMAIL_RE, _hint, snake_case
from etl.dialects import IDENT_RE
from etl.endpoints import Endpoint
from etl.sql_schema import design_table

INT_MAX = 2_147_483_647


def endpoint_for(kind: str, cfg: dict) -> tuple[Endpoint, str]:
    """Translate the agent's connector kwargs into an Endpoint and a table name."""
    if kind == "csv":
        return Endpoint("csv", {"path": cfg["file_path"]}), os.path.basename(cfg["file_path"])
    if kind in ("postgresql", "mysql"):
        return Endpoint(kind, {k: cfg[k] for k in ("host", "port", "database", "username", "password")}), cfg["table_name"]
    if kind in ("duckdb", "sqlite"):
        return Endpoint(kind, {"path": cfg["db_path"]}), cfg["table_name"]
    if kind == "mongodb":
        return Endpoint("mongodb", {"uri": cfg["connection_string"], "database": cfg["database"]}), cfg["collection"]
    raise ValueError(f"Unsupported endpoint kind {kind!r}")


def safe_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Make every column a valid SQL identifier (the plan may have skipped normalize_columns)."""
    names, seen, renamed = [], set(), []
    for c in df.columns:
        n = str(c)
        if not IDENT_RE.match(n):
            n = snake_case(n)
            if not n[0].isalpha() and n[0] != "_":
                n = f"c_{n}"
            n = n[:48]
        base, k = n, 1
        while n in seen:
            k += 1
            n = f"{base[:45]}_{k}"
        seen.add(n)
        names.append(n)
        if n != c:
            renamed.append((c, n))
    out = df.copy()
    out.columns = names
    return out, renamed


def _passes(series, sem):
    rule = DOMAIN_RULES[sem][1]
    return bool(series.map(rule).all())


def infer_semantics(df: pd.DataFrame) -> tuple[dict, str | None]:
    """
    Semantic type per column of an already-cleaned, typed DataFrame.
    A domain rule (money >= 0, quantity > 0, ...) is only proposed when every
    value already satisfies it, so the CHECK constraint documents the data
    instead of rejecting the load.
    """
    pk = None
    for col in df.columns:
        s = df[col]
        if (col == "id" or col.endswith("_id")) and len(s) and s.notna().all() and s.is_unique:
            pk = col
            break

    semantics = {pk: "pk"} if pk else {}
    for col in df.columns:
        if col == pk:
            continue
        s = df[col]
        nn = s.dropna()
        hint = _hint(col)
        if pd.api.types.is_bool_dtype(s):
            semantics[col] = "bool"
        elif pd.api.types.is_datetime64_any_dtype(s):
            semantics[col] = "datetime" if (nn.dt.normalize() != nn).any() else "date"
        elif pd.api.types.is_numeric_dtype(s):
            integral = pd.api.types.is_integer_dtype(s)
            if hint in DOMAIN_RULES and (hint not in ("quantity", "age") or integral) and len(nn) and _passes(nn, hint):
                semantics[col] = hint
            elif integral:
                semantics[col] = "bigint" if len(nn) and nn.abs().max() > INT_MAX else "int"
            else:
                semantics[col] = "float"
        elif hint == "email" and len(nn) and nn.astype(str).str.match(EMAIL_RE).all():
            semantics[col] = "email"
        else:
            semantics[col] = "text"
    return semantics, pk


def _scalars(df: pd.DataFrame) -> pd.DataFrame:
    """Nested values (dicts/lists from JSON sources) are stored as JSON text."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v)
    return out


def load_and_verify(source_type, source_config, target_type, target_config, source_rows: int,
                    df: pd.DataFrame, execution_log: list, label: str = "AI plan") -> dict:
    """Design the schema for the cleaned data, load it atomically, record the run and verify it."""
    started = datetime.now()
    source, source_table = endpoint_for(source_type, source_config)
    target, table = endpoint_for(target_type, target_config)
    df, renamed = safe_columns(_scalars(df).reset_index(drop=True))
    semantics, pk = infer_semantics(df)
    date_cols = [c for c, sem in semantics.items() if sem in ("date", "datetime")]
    td = design_table(df, table, semantics, pk, date_cols[:1])
    plan = [(td, df)]

    probe = None
    if date_cols:
        sample = df[date_cols[0]].dropna()
        if len(sample):
            v = sample.iloc[len(sample) // 2]
            probe = (table, date_cols[0], v.date().isoformat() if semantics[date_cols[0]] == "date" else str(v))

    removed = source_rows - len(df)
    stats = {"source_rows": source_rows, "loaded_rows": len(df), "exact_duplicates_removed": removed,
             "quarantined_rows": 0, "removed_label": "rows removed by the plan"}
    steps = [{"column": (e.get("details") or {}).get("column") or e.get("column"),
              "action": e["action"], "detail": f"{label}: {e['status']}"}
             for e in execution_log if e.get("status") in ("success", "error")]
    steps += [{"column": old, "action": "rename_for_sql", "detail": f"'{old}' -> '{new}'"} for old, new in renamed]

    loader = mongo_loader if target.kind == "mongodb" else sql_loader
    loader.ensure_metadata_tables(target)
    run = {"started_at": started, "source_system": source.kind, "source_table": source_table[:64],
           "target_system": target.kind, "target_table": table, "mode": "flat",
           "source_rows": source_rows, "loaded_rows": len(df), "duplicates_removed": removed,
           "quarantined_rows": 0, "steps": steps, "quarantine": None}
    try:
        load = loader.staged_load(target, plan, explain_probe=probe)
    except sql_loader.LoadError as e:
        run.update(status="failed", finished_at=datetime.now(), loaded_rows=0, error=str(e)[:2000], checksum=None)
        try:
            loader.record_run(target, run)
        except Exception:
            pass
        raise
    run.update(status="success", finished_at=datetime.now(), error=None,
               checksum=load["tables"][table]["expected_checksum"])
    run_id = loader.record_run(target, run)
    checks = loader.verify_migration(target, source, source_table, plan, load, stats)
    target_info = loader.describe_target(target, plan)[table]
    return {
        "run_id": run_id,
        "table": table,
        "primary_key": pk,
        "semantics": semantics,
        "renamed_columns": renamed,
        "ddl": load["ddl"][table],
        "ddl_from_catalog": target_info.get("ddl"),
        "protocol": load["protocol"],
        "explain": load["explain"],
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }
