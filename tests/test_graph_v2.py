import pytest
import os
import uuid
from graph import graph, run_migration
from migration_service import start_migration, get_agent_state, resume_migration

def test_v2_graph_interrupt():
    """Test that the graph pauses at human_review and can be resumed."""
    thread_id = str(uuid.uuid4())
    
    initial_state = {
        "query": "Test migration",
        "source_type": "csv",
        "target_type": "duckdb",
        "source_config": {"file_path": "data/enterprise.csv"},
        "target_config": {"db_path": "test_graph.duckdb", "table_name": "test_table"},
        "table_name": "test_table",
        "plan_approved": False,
        "executed_steps": [],
        "timings": {},
        "validations": ["row_count"]
    }
    
    # Start graph (should pause at human_review)
    start_migration(thread_id, initial_state)
    
    snapshot = get_agent_state(thread_id)
    assert "human_review" in snapshot.next, "Graph did not interrupt before human_review"
    assert "migration_analyst" in snapshot.values["executed_steps"]
    
    # Resume with approval
    resume_migration(thread_id, plan_approved=True)
    
    snapshot = get_agent_state(thread_id)
    assert len(snapshot.next) == 0, "Graph did not complete"
    assert "reporter" in snapshot.values["executed_steps"]
    assert "supervisor" in snapshot.values["executed_steps"]

def test_legacy_run_migration_wrapper():
    """Test that the backward-compatible run_migration auto-approves."""
    result = run_migration(
        source_type="csv",
        target_type="duckdb",
        source_config={"file_path": "data/enterprise.csv"},
        target_config={"db_path": "test_legacy.duckdb", "table_name": "legacy_table"},
        validations=[]
    )
    
    assert result.get("success") is not None
    assert "migration_executor" in result.get("executed_steps", [])
    
    # Cleanup
    if os.path.exists("test_legacy.duckdb"):
        os.remove("test_legacy.duckdb")
