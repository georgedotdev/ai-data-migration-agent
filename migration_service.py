"""
Migration Service Layer

Provides helper functions for the Streamlit UI to interact with
the deterministic ETL pipeline and the LangGraph workflow.
"""

import os
import pandas as pd
from connectors.postgres_connector import PostgreSQLConnector
from connectors.mysql_connector import MySQLConnector
from etl.transform import run_deterministic_pipeline


def run_migration(
    source_table: str,
    target_table: str,
    pg_config: dict = None,
    mysql_config: dict = None
) -> dict:
    """
    Execute deterministic data migration from PostgreSQL to MySQL.

    1. Connects to PostgreSQL and extracts the source table as a DataFrame
    2. Records row count before cleaning
    3. Runs run_deterministic_pipeline(df)
    4. Records row count after cleaning
    5. Writes the cleaned DataFrame to MySQL target table
    6. Returns a result dict containing:
       source_rows, target_rows, transformation_log, status, source_table, target_table
    """
    source_table = (source_table or "").strip()
    target_table = (target_table or "").strip()

    if not source_table:
        return {
            "status": "error",
            "source_table": source_table,
            "target_table": target_table,
            "source_rows": 0,
            "target_rows": 0,
            "transformation_log": [],
            "error": "Source table name cannot be empty.",
            "message": "Source table name cannot be empty."
        }

    if not target_table:
        return {
            "status": "error",
            "source_table": source_table,
            "target_table": target_table,
            "source_rows": 0,
            "target_rows": 0,
            "transformation_log": [],
            "error": "Target table name cannot be empty.",
            "message": "Target table name cannot be empty."
        }

    # Step 1: Connect to PostgreSQL and extract source table
    try:
        pg_conn = PostgreSQLConnector(table_name=source_table, **(pg_config or {}))
        source_df = pg_conn.extract_table(source_table)
    except Exception as e:
        return {
            "status": "error",
            "source_table": source_table,
            "target_table": target_table,
            "source_rows": 0,
            "target_rows": 0,
            "transformation_log": [],
            "error": f"PostgreSQL extraction failed: {str(e)}",
            "message": f"Could not extract data from PostgreSQL table '{source_table}'. Error: {str(e)}"
        }

    # Step 2: Record row count before cleaning
    source_rows = len(source_df)
    source_preview = source_df.head(10).copy()

    # Step 3: Run deterministic transformation pipeline
    try:
        cleaned_df, transformation_log = run_deterministic_pipeline(source_df)
    except Exception as e:
        return {
            "status": "error",
            "source_table": source_table,
            "target_table": target_table,
            "source_rows": source_rows,
            "target_rows": 0,
            "transformation_log": [],
            "error": f"Data transformation failed: {str(e)}",
            "message": f"Transformation pipeline error: {str(e)}"
        }

    # Step 4: Record row count after cleaning
    target_rows = len(cleaned_df)
    target_preview = cleaned_df.head(10).copy()

    # Step 5: Write cleaned DataFrame to MySQL target table
    try:
        mysql_conn = MySQLConnector(table_name=target_table, **(mysql_config or {}))
        mysql_conn.write_data(cleaned_df, table_name=target_table)
    except Exception as e:
        return {
            "status": "error",
            "source_table": source_table,
            "target_table": target_table,
            "source_rows": source_rows,
            "target_rows": target_rows,
            "transformation_log": transformation_log,
            "source_preview": source_preview,
            "target_preview": target_preview,
            "error": f"MySQL write failed: {str(e)}",
            "message": f"Data was cleaned ({target_rows} rows) but writing to MySQL table '{target_table}' failed: {str(e)}"
        }

    # Step 6: Return complete migration result dict
    return {
        "status": "success",
        "source_table": source_table,
        "target_table": target_table,
        "source_rows": source_rows,
        "target_rows": target_rows,
        "transformation_log": transformation_log,
        "source_preview": source_preview,
        "target_preview": target_preview,
        "message": f"Successfully migrated {target_rows} rows from PostgreSQL table '{source_table}' to MySQL table '{target_table}'."
    }


# ─────────────────────────────────────────────
# LangGraph Workflow Helpers (Preserved)
# ─────────────────────────────────────────────

try:
    from graph import graph

    def start_migration(thread_id: str, initial_state: dict):
        """Start the LangGraph workflow up to the human review breakpoint."""
        config = {"configurable": {"thread_id": thread_id}}
        return graph.invoke(initial_state, config=config)

    def get_agent_state(thread_id: str):
        """Retrieve current state snapshot from MemorySaver checkpointer."""
        config = {"configurable": {"thread_id": thread_id}}
        return graph.get_state(config)

    def resume_migration(thread_id: str, plan_approved: bool, human_feedback: str = "", rejected_steps: list = None):
        """Resume the LangGraph workflow with human feedback."""
        if rejected_steps is None:
            rejected_steps = []
        config = {"configurable": {"thread_id": thread_id}}
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
