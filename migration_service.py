"""
Migration Service Layer

Thin orchestration layer between the Streamlit dashboard and the
LangGraph migration engine. This module:

- Generates AI-powered migration plans via ai_planner
- Handles target artifact generation (DuckDB auto-create)
- Passes connector configs to the engine
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
from ai_planner import generate_plan


REPORTS_DIR = "reports"
GENERATED_DIR = "generated"


def generate_ai_plan(
    user_request,
    source_type="csv",
    source_config=None,
    target_type_hint=None,
    has_target_config=False,
    api_key=None
):
    """
    Generate an AI migration plan for dashboard display.

    1. Discovers schema from source connector
    2. Calls ai_planner.generate_plan()
    3. Returns plan + schema for review

    The plan is NOT executed here — the user reviews it first.
    """

    if source_config is None:
        source_config = {}

    # Determine filename for the planner
    if source_type.lower() == "csv":
        filename = os.path.basename(
            source_config.get("file_path", "unknown.csv")
        )
    elif source_type.lower() == "postgresql":
        filename = source_config.get(
            "table_name", "pg_table"
        )
    elif source_type.lower() == "mongodb":
        filename = source_config.get(
            "collection", "mongo_collection"
        )
    else:
        filename = "unknown"

    # Discover schema via connector
    schema = discover_schema(source_type, source_config)

    # Generate plan (AI or deterministic fallback)
    plan = generate_plan(
        user_request=user_request,
        filename=filename,
        schema=schema,
        api_key=api_key,
        source_type_hint=source_type,
        target_type_hint=target_type_hint,
        has_target_config=has_target_config
    )

    return {
        "plan": plan,
        "schema": schema
    }


def run_full_migration(
    source_type="csv",
    target_type="duckdb",
    source_config=None,
    target_config=None,
    table_name="enterprise",
    transformations=None,
    validations=None,
    generate_target=False
):
    """
    Full migration orchestrator.

    1. Handles target artifact generation if needed
    2. Discovers schema from source
    3. Executes the LangGraph workflow
    4. Builds and saves a report
    5. Returns structured result for the dashboard
    """

    if source_config is None:
        source_config = {"file_path": "data/enterprise.csv"}
    if target_config is None:
        target_config = {}

    output_file_path = ""

    # ---------------------------------
    # Target Artifact Generation
    # ---------------------------------
    if generate_target and target_type.lower() == "duckdb":
        os.makedirs(GENERATED_DIR, exist_ok=True)
        generated_filename = f"{table_name}.duckdb"
        generated_path = os.path.join(
            GENERATED_DIR, generated_filename
        )
        # Remove old file if exists
        if os.path.exists(generated_path):
            os.remove(generated_path)

        target_config = {
            "db_path": generated_path,
            "table_name": table_name
        }
        output_file_path = generated_path
        print(
            f"[SERVICE] Generating DuckDB target: "
            f"{generated_path}"
        )

    # Ensure target_config has table_name for DuckDB
    if (
        target_type.lower() == "duckdb"
        and "table_name" not in target_config
    ):
        target_config["table_name"] = table_name

    # ---------------------------------
    # Schema Discovery
    # ---------------------------------
    schema_start = time.time()
    schema = discover_schema(source_type, source_config)
    schema_time = round(time.time() - schema_start, 4)

    # ---------------------------------
    # Run LangGraph Workflow
    # ---------------------------------
    result = run_migration(
        source_type=source_type,
        target_type=target_type,
        source_config=source_config,
        target_config=target_config,
        table_name=table_name,
        transformations=transformations,
        validations=validations,
        output_file_path=output_file_path
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
        "source_config": _sanitize_config(source_config),
        "target_config": _sanitize_config(target_config),
        "table_name": table_name,
        "schema": schema,
        "executed_steps": result.get("executed_steps", []),
        "success": result.get("success", False),
        "validation_results": result.get(
            "validation_results", {}
        ),
        "timings": result.get("timings", {}),
        "transformations": transformations,
        "validations": validations,
        "output_file_path": output_file_path
    }

    # ---------------------------------
    # Save Report
    # ---------------------------------
    report_path = save_report(report)
    report["_report_path"] = report_path

    return {
        "schema": schema,
        "result": result,
        "report": report,
        "output_file_path": output_file_path
    }


def _sanitize_config(config):
    """Remove sensitive fields (passwords) from config for reports."""
    if not config:
        return {}
    sanitized = dict(config)
    if "password" in sanitized:
        sanitized["password"] = "***"
    return sanitized


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

    for filename in sorted(
        os.listdir(REPORTS_DIR), reverse=True
    ):
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
