import time
from connectors.postgres_connector import PostgreSQLConnector
import pandas as pd
import traceback

def run_trace():
    print("EXECUTOR_START")
    
    source_df = pd.DataFrame({'a': [1,2,3]})
    print(f"SOURCE_ROWS: {len(source_df)}")
    
    target_config = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "migration_db",
        "username": "migration",
        "password": "migration123",
        "table_name": "enterprise_migrated"
    }
    
    target = PostgreSQLConnector(**target_config)
    print(f"TARGET_TABLE: {target.table_name}")
    print(f"CONNECTING_TO_POSTGRES: {target.connection_string}")
    
    print("TABLE_CREATE_START")
    try:
        target.write_data(source_df)
        print("TABLE_CREATE_SUCCESS")
    except Exception as e:
        print(f"FAILED TO WRITE: {e}")
        traceback.print_exc()

    print("--- RECONCILER TRACE ---")
    print(f"TARGET_DATABASE: {target.database}")
    print(f"TARGET_TABLE: {target.table_name}")
    try:
        df = target.read_data()
        print(f"ROWS_FOUND: {len(df)}")
    except Exception as e:
        print(f"RECONCILER FAILED: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    run_trace()
