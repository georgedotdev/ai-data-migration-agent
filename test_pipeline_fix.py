import os
import duckdb
from graph import graph

def test_freelancers():
    print("Testing global_freelancers_raw.csv...")
    initial_state = {
        "query": "Migrate data from global_freelancers_raw.csv",
        "source_type": "csv",
        "target_type": "duckdb",
        "source_config": {"file_path": "global_freelancers_raw.csv"},
        "target_config": {"db_path": "migration_test.duckdb", "table_name": "global_freelancers_raw"},
        "table_name": "global_freelancers_raw",
        "plan_approved": False,
        "executed_steps": [],
        "timings": {}
    }
    
    config = {"configurable": {"thread_id": "test_fix_123"}}
    
    print("Running initial pass...")
    graph.invoke(initial_state, config=config)
    
    print("Approving plan...")
    graph.update_state(config, {"plan_approved": True})
    
    print("Executing plan...")
    final_state = graph.invoke(None, config=config)
    
    print("\n--- Output Rows ---")
    try:
        conn = duckdb.connect("migration_test.duckdb")
        count = conn.execute("SELECT count(*) FROM global_freelancers_raw").fetchone()[0]
        print(f"Total rows in DuckDB: {count}")
    except Exception as e:
        print(f"Error checking DuckDB: {e}")

if __name__ == "__main__":
    test_freelancers()
