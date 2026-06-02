"""
LangGraph Migration Workflow

Multi-connector migration orchestration via StateGraph.

Topology (unchanged):
    planner → retriever → executor → tester → supervisor

The executor and tester now use the connector factory to
instantiate source/target connectors dynamically from
source_type, target_type, source_config, and target_config
stored in AgentState.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END

from connectors.connector_factory import get_connector
from etl.transform import transform_data
from etl.rollback import rollback_migration
from etl.schema import discover_schema

from validation.run_validations import run_all_validations

import time


class AgentState(TypedDict):
    query: str
    plan: list[str]
    executed_steps: list[str]
    context: str
    success: bool
    source_type: str
    target_type: str
    source_config: dict
    target_config: dict
    table_name: str
    timings: dict
    validation_results: dict
    transformations: list[str]
    validations: list[str]
    output_file_path: str


def planner(state: AgentState):
    start = time.time()

    result = {
        "plan": ["extract", "transform", "load"]
    }

    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["planner"] = round(elapsed, 4)
    result["timings"] = timings

    return result


def retriever(state: AgentState):
    start = time.time()

    source_type = state.get("source_type", "csv")
    source_config = state.get("source_config") or {}

    # Backward compatibility: if source_config has file_path
    if not source_config and source_type.lower() == "csv":
        source_config = {
            "file_path": "data/enterprise.csv"
        }

    schema = discover_schema(source_type, source_config)

    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["schema_discovery"] = round(elapsed, 4)

    return {
        "context": str(schema),
        "timings": timings
    }


def executor(state: AgentState):
    if not state["plan"]:
        return {}

    start = time.time()
    step = state["plan"][0]

    source_type = state.get("source_type", "csv").lower()
    target_type = state.get("target_type", "duckdb").lower()
    source_config = state.get("source_config") or {}
    target_config = state.get("target_config") or {}
    transformations = state.get("transformations") or None

    # Build connectors via factory
    source = get_connector(source_type, **source_config)
    target = get_connector(target_type, **target_config)

    if step == "extract":
        df = source.read_data()
        print(f"Extracted {len(df)} rows.")

    elif step == "load":

        df = source.read_data()

        transformed_df = transform_data(
            df, transformations=transformations
        )

        max_retries = 3

        for attempt in range(max_retries):

            try:

                target.write_data(transformed_df)
                print("[LOAD] Migration successful")

                break

            except Exception as e:

                print(f"[LOAD] Attempt {attempt + 1} failed")
                print(f"[LOAD] Error: {e}")

                if attempt < max_retries - 1:

                    print("[LOAD] Retrying in 2 seconds...")
                    time.sleep(2)

                else:

                    print("[LOAD] All retries exhausted")

                    raise e

    elif step == "transform":

        df = source.read_data()

        transformed_df = transform_data(
            df, transformations=transformations
        )

        print("Transformation completed.")

    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings[step] = round(elapsed, 4)

    return {
        "plan": state["plan"][1:],
        "executed_steps": state["executed_steps"] + [step],
        "timings": timings
    }


def should_continue(state: AgentState):
    if state["plan"]:
        return "executor"
    return "tester"


def tester(state: AgentState):
    start = time.time()

    print("Running validations...")

    source_type = state.get("source_type", "csv").lower()
    target_type = state.get("target_type", "duckdb").lower()
    source_config = state.get("source_config") or {}
    target_config = state.get("target_config") or {}
    validations_list = state.get("validations") or None
    transformations = state.get("transformations") or None

    # Build connectors for validation
    source = get_connector(source_type, **source_config)
    target = get_connector(target_type, **target_config)

    validation_results = run_all_validations(
        source_connector=source,
        target_connector=target,
        validations=validations_list,
        transformations=transformations
    )

    if not validation_results["overall_success"]:
        target_for_rollback = get_connector(
            target_type, **target_config
        )
        rollback_migration(target_for_rollback)

    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["validate"] = round(elapsed, 4)

    return {
        "success": validation_results["overall_success"],
        "validation_results": validation_results,
        "timings": timings
    }


def supervisor(state: AgentState):
    return {}


builder = StateGraph(AgentState)

builder.add_node("planner", planner)
builder.add_node("retriever", retriever)
builder.add_node("executor", executor)
builder.add_node("tester", tester)
builder.add_node("supervisor", supervisor)

builder.set_entry_point("planner")

builder.add_edge("planner", "retriever")
builder.add_edge("retriever", "executor")

builder.add_conditional_edges(
    "executor",
    should_continue,
    {
        "executor": "executor",
        "tester": "tester"
    }
)
builder.add_edge("tester", "supervisor")
builder.add_edge("supervisor", END)

graph = builder.compile()


def run_migration(
    source_type="csv",
    target_type="duckdb",
    source_config=None,
    target_config=None,
    table_name="enterprise",
    transformations=None,
    validations=None,
    output_file_path=""
):
    """
    Run the full migration workflow.

    Args:
        source_type: Connector type ('csv', 'duckdb', 'postgresql', 'mongodb')
        target_type: Connector type ('duckdb', 'postgresql', 'mongodb')
        source_config: Dict of connection params for source connector
        target_config: Dict of connection params for target connector
        table_name: Name for the target table/collection
        transformations: List of transforms to apply (or None for all)
        validations: List of validations to run (or None for all)
        output_file_path: Path to generated output file (DuckDB only)
    """

    # Defaults for backward compatibility
    if source_config is None:
        source_config = {"file_path": "data/enterprise.csv"}
    if target_config is None:
        target_config = {
            "db_path": "migration.duckdb",
            "table_name": table_name
        }

    total_start = time.time()

    initial_state = {
        "query": f"Migrate {table_name} data",
        "plan": [],
        "executed_steps": [],
        "context": "",
        "success": False,
        "source_type": source_type,
        "target_type": target_type,
        "source_config": source_config,
        "target_config": target_config,
        "table_name": table_name,
        "timings": {},
        "validation_results": {},
        "transformations": transformations or [
            "normalize_columns",
            "handle_nulls",
            "type_conversion"
        ],
        "validations": validations or [
            "row_count",
            "checksum"
        ],
        "output_file_path": output_file_path
    }

    result = graph.invoke(initial_state)

    timings = dict(result.get("timings") or {})
    timings["total"] = round(time.time() - total_start, 4)
    result["timings"] = timings

    return result


if __name__ == "__main__":
    result = run_migration()
    print(result)