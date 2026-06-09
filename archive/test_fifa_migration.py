import os
from dotenv import load_dotenv
load_dotenv()

from migration_service import start_migration, get_agent_state, resume_migration
import pandas as pd
import time

def run_fifa():
    print("============================================================")
    print("Running Flow: FIFA -> POSTGRESQL (GEMINI AUDIT)")
    print("============================================================")

    # 1. Start migration
    thread_id = "test_fifa_gemini_" + str(int(time.time()))
    source_config = {"file_path": "data/fifa21_raw_data.csv"}
    target_config = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "migration_db",
        "username": "migration",
        "password": "migration123",
        "table_name": "fifa21_gemini_migrated"
    }

    initial_state = {
        "query": "Migrate data from CSV to PostgreSQL",
        "source_type": "CSV",
        "target_type": "PostgreSQL",
        "source_config": source_config,
        "target_config": target_config,
        "table_name": "fifa21_gemini_migrated",
        "plan_approved": False,
        "executed_steps": [],
        "timings": {}
    }
    
    print("Executing up to human review...")
    state = start_migration(
        thread_id=thread_id,
        initial_state=initial_state
    )

    # Output what Gemini generated
    print("--- GEMINI OUTPUTS ---")
    print(f"Assessment exists: {bool(state.get('assessment'))}")
    print(f"DSL Transformation exists: {bool(state.get('transformation_dsl'))}")
    
    # 2. Approve plan
    print("Approving plan...")
    final_state = resume_migration(
        thread_id=thread_id,
        plan_approved=True,
        human_feedback=None,
        rejected_steps=[]
    )

    print("--- MIGRATION COMPLETE ---")
    print("Reconciliation:")
    print(final_state.get('reconciliation_report'))

if __name__ == "__main__":
    run_fifa()
