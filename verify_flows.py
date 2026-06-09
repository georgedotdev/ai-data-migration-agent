import os
import sys
import uuid
import time
from graph import graph

def run_migration_flow(source_type, target_type, source_config, target_config, table_name="enterprise_test"):
    print(f"============================================================")
    print(f"Running Flow: {source_type.upper()} -> {target_type.upper()}")
    print(f"============================================================")
    
    initial_state = {
        "query": f"Migrate data from {source_type} to {target_type}",
        "source_type": source_type,
        "target_type": target_type,
        "source_config": source_config,
        "target_config": target_config,
        "table_name": table_name,
        "plan_approved": False,
        "executed_steps": [],
        "timings": {}
    }

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 1. Run up to Human Review
    print("Executing up to human review...")
    try:
        state_iter = graph.invoke(initial_state, config=config)
    except Exception as e:
        print(f"Failed during initial graph execution: {e}")
        return False
        
    print(f"Pending tasks (should be human_review): {graph.get_state(config).next}")
    
    current_state = graph.get_state(config).values
    
    # Verify required artifacts exist
    print("Verifying assessment...")
    if "assessment" not in current_state or not current_state["assessment"]:
        print("FAIL: Assessment not generated.")
        return False
        
    print("Verifying preview...")
    if "preview" not in current_state or current_state["preview"] is None:
        print("FAIL: Preview not generated.")
        return False

    print("Approving plan...")
    # 2. Modify state to approve plan and resume
    resume_state = {
        "plan_approved": True,
        "human_feedback": ""
    }
    graph.update_state(config, resume_state)
    
    print("Resuming execution...")
    try:
        final_state = graph.invoke(None, config=config)
    except Exception as e:
        print(f"Failed during execution: {e}")
        return False
        
    print("Verifying success...")
    if not final_state.get("success"):
        print(f"FAIL: Migration unsuccessful. Reconciliation: {final_state.get('reconciliation')}")
        return False
        
    print("Verifying executive report...")
    if "report" not in final_state or not final_state["report"]:
        print("FAIL: Executive report not generated.")
        return False
        
    print(f"SUCCESS! {source_type.upper()} -> {target_type.upper()} flow completed successfully.")
    print(f"Reconciliation: {final_state.get('reconciliation')}")
    return True

if __name__ == "__main__":
    success = True
    
    # Set fallback to deterministic for predictable fast tests without keys
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    
    # FLOW A: CSV -> PostgreSQL
    csv_config = {"file_path": "data/enterprise.csv"}
    pg_config = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "migration_db",
        "username": "migration",
        "password": "migration123",
        "table_name": "flow_a_test"
    }
    
    print("Testing Flow A: CSV -> PostgreSQL")
    if not run_migration_flow("csv", "postgresql", csv_config, pg_config, "flow_a_test"):
        success = False
        print("Flow A failed.")
        
    # FLOW B: CSV -> DuckDB
    duck_config = {
        "db_path": "migration_test.duckdb",
        "table_name": "flow_b_test"
    }
    print("\nTesting Flow B: CSV -> DuckDB")
    if not run_migration_flow("csv", "duckdb", csv_config, duck_config, "flow_b_test"):
        success = False
        print("Flow B failed.")
        
    # FLOW C: MongoDB -> PostgreSQL
    mongo_config = {
        "connection_string": "mongodb://localhost:27017/?serverSelectionTimeoutMS=2000",
        "database": "migration_test",
        "collection": "enterprise_test"
    }
    
    pg_config_c = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "migration_db",
        "username": "migration",
        "password": "migration123",
        "table_name": "flow_c_test"
    }
    
    print("\nTesting Flow C: MongoDB -> PostgreSQL")
    if not run_migration_flow("mongodb", "postgresql", mongo_config, pg_config_c, "flow_c_test"):
        success = False
        print("Flow C failed.")
        
    if not success:
        sys.exit(1)
    
    print("\nAll Stability Gate flows passed!")
    sys.exit(0)
