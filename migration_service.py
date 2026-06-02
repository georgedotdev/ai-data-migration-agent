"""
Migration Service Layer

Thin orchestration layer between the Streamlit dashboard and the
LangGraph migration engine. This module:

- Accepts connector-oriented parameters (source_type, target_type)
- Runs schema discovery via etl/schema.py
- Invokes the LangGraph workflow via graph.py
- Persists JSON reports to reports/
- Loads historical reports for the dashboard

No business logic lives here — it delegates everything to existing modules.
"""

import os
import json
import time
from datetime import datetime

from etl.schema import discover_schema
from graph import run_migration


REPORTS_DIR = "reports"


def run_full_migration(
    source_type="CSV",
    target_type="DuckDB",
    source_path="data/enterprise.csv",
    db_path="migration.duckdb",
    table_name="enterprise"
):
    """
    Full migration orchestrator.

    1. Discovers schema from source
    2. Executes the LangGraph workflow
    3. Builds and saves a report
    4. Returns structured result for the dashboard
    """

    # ---------------------------------
    # Schema Discovery
    # ---------------------------------
    schema_start = time.time()
    schema = discover_schema(source_path)
    schema_time = round(time.time() - schema_start, 4)

    # ---------------------------------
    # Run LangGraph Workflow
    # ---------------------------------
    result = run_migration(
        source_type=source_type,
        target_type=target_type,
        source_path=source_path,
        db_path=db_path,
        table_name=table_name
    )

    # Inject schema discovery time
    timings = dict(result.get("timings") or {})
    timings["schema_discovery"] = schema_time
    result["timings"] = timings

    # ---------------------------------
    # Build Report
    # ---------------------------------
    report = {
        "timestamp": datetime.now().isoformat(),
        "source_type": source_type,
        "target_type": target_type,
        "source_path": source_path,
        "db_path": db_path,
        "table_name": table_name,
        "schema": schema,
        "executed_steps": result.get("executed_steps", []),
        "success": result.get("success", False),
        "validation_results": result.get("validation_results", {}),
        "timings": result.get("timings", {})
    }

    # ---------------------------------
    # Save Report
    # ---------------------------------
    report_path = save_report(report)
    report["_report_path"] = report_path

    return {
        "schema": schema,
        "result": result,
        "report": report
    }


def save_report(report):
    """Save migration report as JSON to reports/ directory."""

    os.makedirs(REPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    filename = f"migration_{timestamp}.json"
    filepath = os.path.join(REPORTS_DIR, filename)

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"[REPORT] Saved to {filepath}")
    return filepath


def load_reports():
    """Load all historical migration reports, newest first."""

    if not os.path.exists(REPORTS_DIR):
        return []

    reports = []

    for filename in sorted(os.listdir(REPORTS_DIR), reverse=True):
        if filename.endswith(".json"):
            filepath = os.path.join(REPORTS_DIR, filename)
            try:
                with open(filepath, "r") as f:
                    report = json.load(f)
                    report["_filename"] = filename
                    reports.append(report)
            except (json.JSONDecodeError, IOError):
                continue

    return reports
