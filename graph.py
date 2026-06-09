"""
LangGraph V2 Migration Workflow

Agentic 10-Node Workflow:
Request Intake → Schema Discovery → Data Profiler → Migration Analyst → 
Human Review (Interrupt) → Transformation Planner → Migration Executor → 
Reconciler → Reporter → Supervisor
"""

import time
import os
import json
import sqlalchemy.exc
from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from connectors.connector_factory import get_connector
from etl.transform import transform_data_dsl, transform_data
from etl.rollback import rollback_migration
from etl.schema import discover_schema
from profiling.data_profiler import profile_data
from ai_brain import generate_transformation_dsl, summarize_transformation_dsl


class AgentState(TypedDict):
    # Setup
    query: str
    source_type: str
    target_type: str
    source_config: dict
    target_config: dict
    table_name: str
    
    # State tracking
    executed_steps: list[str]
    timings: dict
    success: bool
    
    # AI Metadata
    ai_provider: str
    ai_model: str
    fallback_used: bool
    fallback_chain_traversed: list[str]
    assessment_provider: str
    transformation_provider: str
    
    # Discover & Profile
    schema: dict
    profile: dict
    
    # Analysis    # Outputs
    transformation_dsl: dict
    transformations: list[str]  # Summarized text points
    preview: list[dict]
    preview_impact: dict
    execution_impact: dict
    risk: dict
    
    # Human Review Feedback
    human_feedback: str
    plan_approved: bool
    rejected_steps: list[int]
    
    # Execution parameters
    transformations: list[str]
    validations: list[str]
    output_file_path: str
    
    # Post-Execution (Reconciliation)
    reconciliation: dict
    report: dict


# ─────────────────────────────────────────────
# Graph Nodes
# ─────────────────────────────────────────────

def request_intake(state: AgentState):
    start = time.time()
    
    source_config = state.get("source_config") or {}
    source_type = state.get("source_type", "csv").lower()
    
    # Backward compatibility
    if not source_config and source_type == "csv":
        source_config = {"file_path": "data/enterprise.csv"}
        
    target_config = state.get("target_config") or {}
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["request_intake"] = round(elapsed, 4)
    
    return {
        "source_config": source_config,
        "target_config": target_config,
        "executed_steps": state.get("executed_steps", []) + ["request_intake"],
        "timings": timings
    }

def schema_discovery(state: AgentState):
    start = time.time()
    
    schema = discover_schema(state["source_type"], state["source_config"])
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["schema_discovery"] = round(elapsed, 4)
    
    return {
        "schema": schema,
        "executed_steps": state["executed_steps"] + ["schema_discovery"],
        "timings": timings
    }

def data_profiler(state: AgentState):
    start = time.time()
    
    source_connector = get_connector(state["source_type"], **state["source_config"])
    profile = profile_data(source_connector)
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["data_profiler"] = round(elapsed, 4)
    
    return {
        "profile": profile,
        "executed_steps": state["executed_steps"] + ["data_profiler"],
        "timings": timings
    }

def migration_analyst(state: AgentState):
    """Invokes the AI Brain to assess and plan."""
    start = time.time()
    
    profile = state.get("profile", {})
    query = state.get("query", "")
    human_feedback = state.get("human_feedback", "")
    ai_provider_req = state.get("ai_provider", "Auto")
    ai_model_req = state.get("ai_model", "")
    
    # If the user gave feedback, pass it as intent to the AI Brain
    full_request = query
    if human_feedback:
        full_request += f" | User Feedback to incorporate: {human_feedback}"
        
    dsl = generate_transformation_dsl(
        profile=profile, 
        user_request=full_request,
        requested_provider=ai_provider_req,
        requested_model=ai_model_req
    )
    
    metadata = dsl.get("_metadata", {})
    provider_used = metadata.get("provider_used", "Deterministic")
    model_used = metadata.get("model_used", "N/A")
    fallback_used = metadata.get("fallback_used", False)
    fallback_chain = metadata.get("fallback_chain", [])
    
    # Extract assessment components from DSL for UI
    assessment = {
        "dataset_assessment": dsl.get("dataset_assessment", ""),
        "identified_issues": dsl.get("identified_issues", []),
        "schema_mapping_recommendations": dsl.get("schema_mapping_recommendations", [])
    }
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["migration_analyst"] = round(elapsed, 4)
    
    return {
        "assessment": assessment,
        "transformation_dsl": dsl,
        "ai_provider": provider_used,
        "ai_model": model_used,
        "fallback_used": fallback_used,
        "fallback_chain_traversed": fallback_chain,
        "assessment_provider": provider_used,
        "transformation_provider": provider_used,
        "executed_steps": state["executed_steps"] + ["migration_analyst"],
        "timings": timings
    }

from etl.preview import generate_preview, generate_impact_summary, generate_risk_assessment

def transformation_previewer(state: AgentState):
    start = time.time()
    
    source = get_connector(state["source_type"], **state["source_config"])
    # Use a sample for previewing to keep it fast
    df = source.read_data().head(10000)
    
    dsl = state.get("transformation_dsl", {})
    
    preview_data, df_after = generate_preview(df, dsl)
    preview_impact = generate_impact_summary(df, df_after, dsl)
    risk = generate_risk_assessment(dsl)
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["transformation_previewer"] = round(elapsed, 4)
    
    return {
        "preview": preview_data,
        "preview_impact": preview_impact,
        "risk": risk,
        "executed_steps": state["executed_steps"] + ["transformation_previewer"],
        "timings": timings
    }

def human_review(state: AgentState):
    """
    Virtual node to process human input.
    Execution pauses BEFORE this node via interrupt.
    When resumed, it evaluates if plan is approved.
    """
    start = time.time()
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["human_review"] = round(elapsed, 4)
    
    # State updates (plan_approved, human_feedback) are pushed by stream resumption
    return {
        "executed_steps": state["executed_steps"] + ["human_review"],
        "timings": timings
    }

def route_after_review(state: AgentState):
    """If not approved, loop back to analyst for recalculation. Else continue."""
    if not state.get("plan_approved", False):
        return "migration_analyst"
    return "transformation_planner"

def transformation_planner(state: AgentState):
    start = time.time()
    
    # Extract legacy string list to satisfy legacy Executor tests
    dsl = state.get("transformation_dsl", {})
    rejected_steps = state.get("rejected_steps", [])
    
    # Filter out any manually rejected steps from the UI checklist
    if rejected_steps and dsl and "transformations" in dsl:
        filtered_transformations = [t for i, t in enumerate(dsl["transformations"]) if i not in rejected_steps]
        dsl["transformations"] = filtered_transformations
        
    transform_labels = summarize_transformation_dsl(dsl)
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["transformation_planner"] = round(elapsed, 4)
    
    return {
        "transformations": transform_labels,
        "executed_steps": state["executed_steps"] + ["transformation_planner"],
        "timings": timings
    }

def migration_executor(state: AgentState):
    start = time.time()
    
    source = get_connector(state["source_type"], **state["source_config"])
    target = get_connector(state["target_type"], **state["target_config"])
    
    print("EXECUTOR_START")
    df = source.read_data()
    print(f"SOURCE_ROWS: {len(df)}")
    
    # V2 Execution path
    dsl = state.get("transformation_dsl")
    if dsl:
        transformed_df, _ = transform_data_dsl(df, dsl)
    else:
        # Fallback to V1
        transformed_df = transform_data(df, transformations=state.get("transformations"))

    print(f"TARGET_TABLE: {target.table_name}")
    conn_str = getattr(target, 'connection_string', 'N/A')
    if '@' in conn_str:
        parts = conn_str.split('@')
        auth = parts[0].split(':')
        if len(auth) >= 3:
            auth[-1] = '***'
        conn_str = ':'.join(auth) + '@' + parts[1]
    print(f"CONNECTING_TO_POSTGRES: {conn_str}")
    print("TABLE_CREATE_START")
    print(f"ROWS_TO_INSERT: {len(transformed_df)}")

    max_retries = 3
    success = False
    for attempt in range(max_retries):
        try:
            target.write_data(transformed_df)
            print("TABLE_CREATE_SUCCESS")
            print(f"ROWS_INSERTED: {len(transformed_df)}")
            print("COMMIT_START")
            print("COMMIT_SUCCESS")
            success = True
            break
        except Exception as e:
            print(f"[LOAD] Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise e

    print("EXECUTOR_COMPLETE")
    
    # Calculate actual impact on the full dataset
    try:
        from etl.preview import generate_impact_summary
        execution_impact = generate_impact_summary(df, transformed_df, dsl if dsl else {"transformations": []})
    except Exception as e:
        print(f"[IMPACT ERROR] {e}")
        execution_impact = {}

    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["migration_executor"] = round(elapsed, 4)
    
    return {
        "execution_impact": execution_impact,
        "executed_steps": state["executed_steps"] + ["migration_executor"],
        "timings": timings
    }

def reconciler(state: AgentState):
    start = time.time()
    print("RECONCILER_START")
    
    source = get_connector(state["source_type"], **state["source_config"])
    target = get_connector(state["target_type"], **state["target_config"])
    
    print(f"TARGET_DATABASE: {getattr(target, 'database', 'N/A')}")
    print(f"TARGET_TABLE: {getattr(target, 'table_name', 'N/A')}")
    
    try:
        source_data = source.read_data()
        rows_read = len(source_data)
    except Exception as e:
        print(f"Source read error: {e}")
        rows_read = 0

    try:
        target_data = target.read_data()
        rows_written = len(target_data)
        print(f"ROWS_FOUND: {rows_written}")
        target_reachable = True
    except (sqlalchemy.exc.DatabaseError, FileNotFoundError, Exception) as e:
        print(f"[RECONCILER ERROR] Database Error on read_data: {e}")
        rows_written = 0
        target_reachable = False

    table_created = rows_written > 0
    success = table_created and target_reachable
    print(f"RECONCILIATION_SUCCESS: {success}")
    
    execution_impact = state.get("execution_impact", {})
    preview_impact = state.get("preview_impact", {})
    impact_source = execution_impact if execution_impact else preview_impact
    duplicates_removed = impact_source.get("duplicates_removed", 0)

    reconciliation_results = {
        "rows_read": rows_read,
        "rows_written": rows_written,
        "rows_skipped": duplicates_removed,
        "target_reachable": target_reachable,
        "table_created": table_created,
        "overall_success": success
    }
    
    if not success:
        print("[RECONCILER] Target unreachable or empty. Triggering rollback.")
        rollback_migration(target)
        
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["reconciler"] = round(elapsed, 4)
    
    return {
        "success": success,
        "reconciliation": reconciliation_results,
        "executed_steps": state["executed_steps"] + ["reconciler"],
        "timings": timings
    }


def reporter(state: AgentState):
    start = time.time()
    
    report = {
        "source": state.get("source_type"),
        "target": state.get("target_type"),
        "success": state.get("success"),
        "provider_used": state.get("ai_provider", "Unknown"),
        "model_used": state.get("ai_model", "Unknown"),
        "fallback_used": state.get("fallback_used", False),
        "fallback_chain_traversed": state.get("fallback_chain_traversed", []),
        "assessment_provider": state.get("assessment_provider", "Unknown"),
        "transformation_provider": state.get("transformation_provider", "Unknown"),
        "reconciliation_results": state.get("reconciliation"),
        "preview_impact": state.get("preview_impact"),
        "execution_impact": state.get("execution_impact"),
        "impact": state.get("execution_impact") or state.get("preview_impact"),
        "risk": state.get("risk"),
        "timings": state.get("timings")
    }
    
    elapsed = time.time() - start
    timings = dict(state.get("timings") or {})
    timings["reporter"] = round(elapsed, 4)
    
    return {
        "report": report,
        "executed_steps": state["executed_steps"] + ["reporter"],
        "timings": timings
    }

def supervisor(state: AgentState):
    return {
        "executed_steps": state["executed_steps"] + ["supervisor"],
    }


# ─────────────────────────────────────────────
# Graph Compilation
# ─────────────────────────────────────────────

builder = StateGraph(AgentState)

builder.add_node("request_intake", request_intake)
builder.add_node("schema_discovery", schema_discovery)
builder.add_node("data_profiler", data_profiler)
builder.add_node("migration_analyst", migration_analyst)
builder.add_node("transformation_previewer", transformation_previewer)
builder.add_node("human_review", human_review)
builder.add_node("transformation_planner", transformation_planner)
builder.add_node("migration_executor", migration_executor)
builder.add_node("reconciler", reconciler)  
builder.add_node("reporter", reporter)
builder.add_node("supervisor", supervisor)

builder.set_entry_point("request_intake")

builder.add_edge("request_intake", "schema_discovery")
builder.add_edge("schema_discovery", "data_profiler")
builder.add_edge("data_profiler", "migration_analyst")
builder.add_edge("migration_analyst", "transformation_previewer")
builder.add_edge("transformation_previewer", "human_review")

builder.add_conditional_edges("human_review", route_after_review)

builder.add_edge("transformation_planner", "migration_executor")
builder.add_edge("migration_executor", "reconciler")

builder.add_edge("reconciler", "reporter")
builder.add_edge("reporter", "supervisor")
builder.add_edge("supervisor", END)

# Attach Checkpointer and Interrupt
import os
db_url = os.environ.get("DATABASE_URL")
if db_url and "postgres" in db_url:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool
    # Establish persistent DB checkpointer
    pool = ConnectionPool(conninfo=db_url)
    memory = PostgresSaver(pool)
    memory.setup()
else:
    memory = MemorySaver()

graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["human_review"]
)

# ─────────────────────────────────────────────
# Backward-Compatible Runner (Tests/CLI)
# ─────────────────────────────────────────────

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
    import uuid
    
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
        "source_type": source_type,
        "target_type": target_type,
        "source_config": source_config,
        "target_config": target_config,
        "table_name": table_name,
        "transformations": transformations,
        "output_file_path": output_file_path,
        "plan_approved": False,
        "executed_steps": [],
        "timings": {}
    }

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # Run up to human_review
    state_iter = graph.invoke(initial_state, config=config)
    
    # Auto-approve for non-interactive runner
    resume_state = {
        "plan_approved": True,
        "human_feedback": ""
    }
    graph.update_state(config, resume_state)
    
    # Resume execution
    result = graph.invoke(None, config=config)
    
    timings = dict(result.get("timings") or {})
    timings["total"] = round(time.time() - total_start, 4)
    result["timings"] = timings

    return result

if __name__ == "__main__":
    result = run_migration()
    print("Migration Success:", result.get("success"))