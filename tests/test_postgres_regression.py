import pytest
import pandas as pd
from connectors.postgres_connector import PostgreSQLConnector

def test_postgres_quoted_identifier_regression():
    # 1. create table & write rows
    table_name = "My Test-Table"
    
    c = PostgreSQLConnector(
        host="127.0.0.1",
        port=5432,
        database="migration_db",
        username="migration",
        password="migration123",
        table_name=table_name
    )
    
    df = pd.DataFrame({'col1': [1, 2, 3], 'col2': ['A', 'B', 'C']})
    
    try:
        # Write rows
        c.write_data(df)
        
        # Count rows
        count = c.count_rows()
        assert count == 3, f"Expected 3 rows, got {count}"
        
        # Read rows
        read_df = c.read_data()
        assert len(read_df) == 3, "Failed to read data with quoted identifier"
        
        # Schema inspection
        schema = c.get_schema()
        assert len(schema) == 2, "Failed to inspect schema with quoted identifier"
        
        # Cleanup (drop table)
        c.drop_table()
        
        # Verify it's gone by testing exception
        import sqlalchemy.exc
        with pytest.raises(sqlalchemy.exc.DatabaseError):
            c.count_rows()

    except Exception as e:
        if "OperationalError" in str(type(e).__name__):
            pytest.skip(f"PostgreSQL not running: {e}")
        pytest.fail(f"Regression test failed: {e}")
