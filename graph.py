from typing import TypedDict
from langgraph.graph import StateGraph, END

from connectors.csv_connector import CSVConnector
from connectors.duckdb_connector import DuckDBConnector
from etl.extract import extract_csv
from etl.transform import transform_data
from etl.validate import validate_migration
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
    source_path: str
    db_path: str
    table_name: str
    timings: dict
    validation_results: dict


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

    source_path = state.get("source_path", "data/enterprise.csv")
    schema = discover_schema(source_path)

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

    source_path = state.get("source_path", "data/enterprise.csv")
    db_path = state.get("db_path", "migration.duckdb")
    table_name = state.get("table_name", "enterprise")

    source = CSVConnector(source_path)
    target = DuckDBConnector(db_path, table_name)

    if step == "extract":
        df = source.read_data()
        print(f"Extracted {len(df)} rows.")

    elif step == "load":

        df = extract_csv(source_path)

        transformed_df = transform_data(df)

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

        df = extract_csv(source_path)

        transformed_df = transform_data(df)

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

    source_path = state.get("source_path", "data/enterprise.csv")
    db_path = state.get("db_path", "migration.duckdb")
    table_name = state.get("table_name", "enterprise")

    validation_results = run_all_validations(
        source_csv=source_path,
        db_path=db_path,
        table_name=table_name
    )

    if not validation_results["overall_success"]:
        rollback_migration(db_path, table_name)

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
    source_type="CSV",
    target_type="DuckDB",
    source_path="data/enterprise.csv",
    db_path="migration.duckdb",
    table_name="enterprise"
):
    total_start = time.time()

    initial_state = {
        "query": f"Migrate {table_name} data",
        "plan": [],
        "executed_steps": [],
        "context": "",
        "success": False,
        "source_type": source_type,
        "target_type": target_type,
        "source_path": source_path,
        "db_path": db_path,
        "table_name": table_name,
        "timings": {},
        "validation_results": {}
    }

    result = graph.invoke(initial_state)

    timings = dict(result.get("timings") or {})
    timings["total"] = round(time.time() - total_start, 4)
    result["timings"] = timings

    return result


if __name__ == "__main__":
    result = run_migration()
    print(result)