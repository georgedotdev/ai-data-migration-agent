"""
Migration Service Layer

Provides helper functions for the Streamlit UI to interact with
the deterministic migration pipeline and the LangGraph workflow.
"""

import os
import time
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from etl import mongo_loader, sql_loader
from etl.cleaning import clean_for_migration
from etl.endpoints import Endpoint, default_config
from etl.sql_loader import LoadError
from etl.sql_schema import design_normalized, design_table, safe_ident


def _error(message, **extra):
    return {"status": "error", "message": message, "error": message, **extra}


def loader_for(endpoint):
    return mongo_loader if endpoint.kind == "mongodb" else sql_loader


def run_migration(
    source_table: str,
    target_table: str,
    pg_config: dict = None,
    mysql_config: dict = None,
    normalize_column: str = None,
    lookup_table: str = None,
    source: Endpoint = None,
    target: Endpoint = None,
) -> dict:
    """
    Deterministic migration between any supported systems
    (PostgreSQL, MySQL, DuckDB, SQLite, MongoDB; CSV as a source).

    1. Extract the legacy table from the source
    2. Clean, type and validate it (rows that can't be migrated go to quarantine)
    3. Design an explicit schema (types, PK, NOT NULL, CHECK, optional 3NF split + FK)
    4. Load atomically (one transaction with transactional DDL; staging + RENAME on MySQL;
       staging + renameCollection on MongoDB)
    5. Record the run in migration metadata tables/collections in the target
    6. Verify by querying both systems and return the evidence

    pg_config / mysql_config keep the original PostgreSQL -> MySQL call style working.
    """
    started = datetime.now()
    timings = {}
    source = source or Endpoint("postgresql", {**default_config("postgresql"), **(pg_config or {})})
    target = target or Endpoint("mysql", {**default_config("mysql"), **(mysql_config or {})})
    source_table = (source_table or "").strip()
    target_table = (target_table or "").strip()
    if source.kind == "csv" and not source_table:
        source_table = os.path.basename(source.config.get("path", "upload.csv"))
    try:
        if source.kind != "csv":
            safe_ident(source_table)
        safe_ident(target_table)
        if normalize_column:
            safe_ident(lookup_table)
            if lookup_table == target_table:
                raise ValueError("Lookup table name must differ from the target table name.")
        if source.kind == target.kind and source.config == target.config and source_table == target_table:
            raise ValueError("Source and target are the same table; choose a different target name.")
    except ValueError as e:
        return _error(str(e))

    # 1. Extract
    t = time.time()
    try:
        raw_df = source.read_table(source_table)
        source_types = source.column_types(source_table)
    except Exception as e:
        return _error(f"Could not extract '{source_table}' from {source.label}: {getattr(e, 'orig', e)}")
    if raw_df.empty:
        return _error(f"Source '{source_table}' in {source.label} is empty or missing. Seed it first.")
    timings["extract"] = time.time() - t

    # 2. Clean (sources may return typed values; the cleaner works on the legacy text form)
    t = time.time()
    try:
        as_text = raw_df.astype(object).where(raw_df.notna(), "").astype(str)
        cleaned = clean_for_migration(as_text)
    except Exception as e:
        return _error(f"Cleaning failed: {e}")
    df = cleaned.df
    timings["clean"] = time.time() - t

    # 3. Schema design
    date_cols = [c for c, sem in cleaned.semantics.items() if sem in ("date", "datetime")]
    index_cols = date_cols[:1]
    mode = "flat"
    if normalize_column:
        if normalize_column not in df.columns:
            return _error(f"Column '{normalize_column}' not found after cleaning. Columns: {', '.join(df.columns)}")
        lookup_def, lookup_df, main_def, main_df = design_normalized(
            df, target_table, cleaned.semantics, cleaned.primary_key, normalize_column, lookup_table, index_cols)
        plan = [(lookup_def, lookup_df), (main_def, main_df)]
        mode = "normalized"
    else:
        main_def = design_table(df, target_table, cleaned.semantics, cleaned.primary_key, index_cols)
        main_df = df
        plan = [(main_def, main_df)]

    probe = None
    if index_cols:
        sample = main_df[index_cols[0]].dropna()
        if len(sample):
            v = sample.iloc[len(sample) // 2]
            probe = (target_table, index_cols[0],
                     v.date().isoformat() if cleaned.semantics[index_cols[0]] == "date" else str(v))

    raw_for = {v: k for k, v in cleaned.column_map.items()}
    target_dialect = target.dialect if target.is_sql else None
    type_mapping = []
    for td, _ in plan:
        for c in td.columns:
            raw_name = raw_for.get(c.name, raw_for.get(c.name.removesuffix("_id")))
            type_mapping.append({
                "target_table": td.name,
                "source_column": raw_name if raw_name is not None else "(generated)",
                "source_type": source_types.get(raw_name, "text") if raw_name is not None else "-",
                "target_column": c.name,
                "target_type": (target_dialect.map_type(c.sql_type) if target_dialect
                                else str(mongo_loader._bson_type(c.sql_type))),
                "detected_as": c.semantic,
                "null": "NULL" if c.nullable else "NOT NULL",
                "constraint": " / ".join(filter(None, [
                    "PRIMARY KEY" if c.name == td.primary_key else None,
                    (f"CHECK ({c.check(target_dialect)})" if target_dialect else f"validator {c.rule}") if c.rule else None,
                    f"FK -> {c.references[0]}({c.references[1]})" if c.references else None,
                    "UNIQUE" if c.name in td.uniques else None,
                ])),
            })

    # 4. Load
    loader = loader_for(target)
    t = time.time()
    try:
        loader.ensure_metadata_tables(target)
    except Exception as e:
        return _error(f"Could not connect to {target.label}: {getattr(e, 'orig', e)}")

    run = {
        "started_at": started, "source_system": source.kind, "source_table": source_table[:64],
        "target_system": target.kind, "target_table": target_table, "mode": mode,
        "source_rows": cleaned.stats["source_rows"], "loaded_rows": len(main_df),
        "duplicates_removed": cleaned.stats["exact_duplicates_removed"],
        "quarantined_rows": cleaned.stats["quarantined_rows"],
        "steps": cleaned.log, "quarantine": cleaned.quarantine,
    }
    try:
        load = loader.staged_load(target, plan, explain_probe=probe)
    except LoadError as e:
        run.update(status="failed", finished_at=datetime.now(), loaded_rows=0, error=str(e)[:2000], checksum=None)
        try:
            loader.record_run(target, run)
        except Exception:
            pass
        return _error(str(e), transformation_log=cleaned.log, stats=cleaned.stats)
    timings["load"] = time.time() - t

    run.update(status="success", finished_at=datetime.now(), error=None,
               checksum=load["tables"][target_table]["expected_checksum"])
    run_id = loader.record_run(target, run)

    # 5. Verify
    t = time.time()
    checks = loader.verify_migration(target, source, source_table, plan, load, cleaned.stats)
    target_info = loader.describe_target(target, plan)
    history = loader.run_history(target)
    timings["verify"] = time.time() - t

    return {
        "status": "success" if all(c["passed"] for c in checks) else "verification_failed",
        "run_id": run_id,
        "mode": mode,
        "source_system": source.label,
        "target_system": target.label,
        "target_kind": target.kind,
        "source_location": source.describe_location(),
        "target_location": target.describe_location(),
        "source_table": source_table,
        "target_table": target_table,
        "lookup_table": lookup_table if normalize_column else None,
        "normalize_column": normalize_column,
        "dependents": getattr(main_def, "dependents", []),
        "source_rows": cleaned.stats["source_rows"],
        "target_rows": len(main_df),
        "stats": cleaned.stats,
        "transformation_log": cleaned.log,
        "quarantine": cleaned.quarantine,
        "source_preview": raw_df.head(15),
        "target_preview": main_df.head(15),
        "type_mapping": pd.DataFrame(type_mapping),
        "ddl": load["ddl"],
        "explain": load["explain"],
        "protocol": load["protocol"],
        "checks": checks,
        "target_info": target_info,
        "history": history,
        "timings": {k: round(v, 3) for k, v in timings.items()},
        "message": f"Migrated {len(main_df)} rows from {source.label} '{source_table}' to {target.label} '{target_table}'"
                   + (f" (+ lookup '{lookup_table}')" if normalize_column else "") + ".",
    }


# ─────────────────────────────────────────────
# LangGraph Workflow Helpers
# ─────────────────────────────────────────────

try:
    from graph import graph
    GRAPH_IMPORT_ERROR = None
except Exception as _e:   # surface the real reason in the UI instead of hiding it
    graph = None
    GRAPH_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


def _require_graph():
    if graph is None:
        raise RuntimeError(f"LangGraph workflow could not be loaded: {GRAPH_IMPORT_ERROR}")


def start_migration(thread_id: str, initial_state: dict, api_keys: dict = None):
    """Start the LangGraph workflow up to the human review breakpoint."""
    _require_graph()
    config = {"configurable": {"thread_id": thread_id, "api_keys": api_keys or {}}}
    return graph.invoke(initial_state, config=config)


def get_agent_state(thread_id: str):
    """Retrieve current state snapshot from the checkpointer."""
    if graph is None:
        return None
    return graph.get_state({"configurable": {"thread_id": thread_id}})


def resume_migration(thread_id: str, plan_approved: bool, human_feedback: str = "", rejected_steps: list = None,
                     api_keys: dict = None):
    """Resume the LangGraph workflow with human feedback."""
    _require_graph()
    config = {"configurable": {"thread_id": thread_id, "api_keys": api_keys or {}}}
    graph.update_state(config, {
        "plan_approved": plan_approved,
        "human_feedback": human_feedback,
        "rejected_steps": rejected_steps or [],
    })
    return graph.invoke(None, config=config)
