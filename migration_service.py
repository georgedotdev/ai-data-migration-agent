"""
Migration Service Layer

Provides helper functions for the Streamlit UI to interact with
the deterministic ETL pipeline and the LangGraph workflow.
"""

import time
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from connectors.postgres_connector import PostgreSQLConnector
from connectors.mysql_connector import MySQLConnector
from etl.cleaning import clean_for_migration
from etl.mysql_loader import (LoadError, describe_target, ensure_metadata_tables, record_run,
                              run_history, staged_load, verify_migration)
from etl.sql_schema import design_normalized, design_table, safe_ident


def _error(message, **extra):
    return {"status": "error", "message": message, "error": message, **extra}


def run_migration(
    source_table: str,
    target_table: str,
    pg_config: dict = None,
    mysql_config: dict = None,
    normalize_column: str = None,
    lookup_table: str = None,
) -> dict:
    """
    Deterministic PostgreSQL -> MySQL migration.

    1. Extract the legacy table from PostgreSQL
    2. Clean, type and validate it (rows that can't be migrated go to quarantine)
    3. Design an explicit MySQL schema (types, PK, NOT NULL, CHECK, optional 3NF split + FK)
    4. Load through staging tables in one transaction, then swap atomically
    5. Record the run in migration_runs / migration_steps / migration_quarantine
    6. Verify with SQL against both databases and return the evidence
    """
    started = datetime.now()
    timings = {}
    source_table = (source_table or "").strip()
    target_table = (target_table or "").strip()
    try:
        safe_ident(source_table)
        safe_ident(target_table)
        if normalize_column:
            safe_ident(lookup_table)
            if lookup_table == target_table:
                raise ValueError("Lookup table name must differ from the target table name.")
    except ValueError as e:
        return _error(str(e))

    # 1. Extract
    t = time.time()
    try:
        pg = PostgreSQLConnector(table_name=source_table, **(pg_config or {}))
        raw_df = pg.extract_table(source_table)
        source_schema = pg.get_schema(source_table)
    except Exception as e:
        return _error(f"Could not extract '{source_table}' from PostgreSQL: {e}")
    timings["extract"] = time.time() - t

    # 2. Clean
    t = time.time()
    try:
        cleaned = clean_for_migration(raw_df)
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
            return _error(f"Column '{normalize_column}' not found after cleaning.")
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
            probe = (target_table, index_cols[0], v.date().isoformat() if cleaned.semantics[index_cols[0]] == "date" else str(v))

    clean_name = {v: k for k, v in cleaned.column_map.items()}
    pg_types = {r[0]: r[1] for r in source_schema}
    type_mapping = []
    for td, _ in plan:
        for c in td.columns:
            raw_name = clean_name.get(c.name, clean_name.get(c.name.removesuffix("_id"), c.name))
            type_mapping.append({
                "target_table": td.name,
                "source_column": raw_name if raw_name in pg_types else "(generated)",
                "postgres_type": pg_types.get(raw_name, "-"),
                "mysql_column": c.name,
                "mysql_type": c.sql_type,
                "detected_as": c.semantic,
                "null": "NULL" if c.nullable else "NOT NULL",
                "constraint": " / ".join(filter(None, [
                    "PRIMARY KEY" if c.name == td.primary_key else None,
                    f"CHECK ({c.check})" if c.check else None,
                    f"FK -> {c.references[0]}({c.references[1]})" if c.references else None,
                    "UNIQUE" if c.name in td.uniques else None,
                ])),
            })

    # 4. Load
    t = time.time()
    try:
        my = MySQLConnector(table_name=target_table, **(mysql_config or {}))
        ensure_metadata_tables(my.engine)
    except Exception as e:
        return _error(f"Could not connect to MySQL: {e}")

    run = {
        "started_at": started, "source_system": "postgresql", "source_table": source_table,
        "target_table": target_table, "mode": mode,
        "source_rows": cleaned.stats["source_rows"], "loaded_rows": len(main_df),
        "duplicates_removed": cleaned.stats["exact_duplicates_removed"],
        "quarantined_rows": cleaned.stats["quarantined_rows"],
        "steps": cleaned.log, "quarantine": cleaned.quarantine,
    }
    try:
        load = staged_load(my.engine, plan, explain_probe=probe)
    except LoadError as e:
        run.update(status="failed", finished_at=datetime.now(), loaded_rows=0, error=str(e)[:2000], checksum=None)
        try:
            record_run(my.engine, run)
        except Exception:
            pass
        return _error(str(e), transformation_log=cleaned.log, stats=cleaned.stats)
    timings["load"] = time.time() - t

    run.update(status="success", finished_at=datetime.now(), error=None,
               checksum=load["tables"][target_table]["expected_checksum"])
    run_id = record_run(my.engine, run)

    # 5. Verify
    t = time.time()
    checks = verify_migration(my.engine, pg.engine, source_table, plan, load, cleaned.stats)
    target_info = describe_target(my.engine, [td.name for td, _ in plan])
    history = run_history(my.engine)
    timings["verify"] = time.time() - t

    return {
        "status": "success" if all(c["passed"] for c in checks) else "verification_failed",
        "run_id": run_id,
        "mode": mode,
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
        "checks": checks,
        "target_info": target_info,
        "history": history,
        "timings": {k: round(v, 3) for k, v in timings.items()},
        "message": f"Migrated {len(main_df)} rows from PostgreSQL '{source_table}' to MySQL '{target_table}'"
                   + (f" (+ lookup '{lookup_table}')" if normalize_column else "") + ".",
    }


# ─────────────────────────────────────────────
# LangGraph Workflow Helpers (Preserved)
# ─────────────────────────────────────────────

try:
    from graph import graph

    def start_migration(thread_id: str, initial_state: dict, api_keys: dict = None):
        """Start the LangGraph workflow up to the human review breakpoint."""
        config = {"configurable": {"thread_id": thread_id, "api_keys": api_keys or {}}}
        return graph.invoke(initial_state, config=config)

    def get_agent_state(thread_id: str):
        """Retrieve current state snapshot from MemorySaver checkpointer."""
        config = {"configurable": {"thread_id": thread_id}}
        return graph.get_state(config)

    def resume_migration(thread_id: str, plan_approved: bool, human_feedback: str = "", rejected_steps: list = None,
                         api_keys: dict = None):
        """Resume the LangGraph workflow with human feedback."""
        if rejected_steps is None:
            rejected_steps = []
        config = {"configurable": {"thread_id": thread_id, "api_keys": api_keys or {}}}
        resume_state = {
            "plan_approved": plan_approved,
            "human_feedback": human_feedback,
            "rejected_steps": rejected_steps
        }
        graph.update_state(config, resume_state)
        return graph.invoke(None, config=config)

except Exception as _e:
    def start_migration(*args, **kwargs):
        raise RuntimeError("LangGraph workflow unavailable in deterministic demo mode.")

    def get_agent_state(*args, **kwargs):
        return None

    def resume_migration(*args, **kwargs):
        raise RuntimeError("LangGraph workflow unavailable in deterministic demo mode.")
