import json
from graph import run_migration

if __name__ == "__main__":
    print("=== STARTING FULL MIGRATION TRACE ===")
    
    result = run_migration(
        source_type="csv",
        source_config={"file_path": "data/fifa21_raw_data.csv"},
        target_type="postgresql",
        target_config={
            "host": "127.0.0.1",
            "port": 5432,
            "database": "migration_db",
            "username": "migration",
            "password": "migration123",
            "table_name": "fifa21_raw_data"
        },
        table_name="fifa21_raw_data"
    )
    
    print("\n=== EXECUTION FINISHED ===")
    print("SUCCESS:", result.get("success"))
    print("RECONCILIATION:", json.dumps(result.get("reconciliation", {}), indent=2))
