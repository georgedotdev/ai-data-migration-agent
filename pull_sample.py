import pandas as pd
from sqlalchemy import create_engine

engine = create_engine('postgresql+psycopg2://migration:migration123@127.0.0.1:5432/migration_db')
table_name = "messy_ecommerce_sales_data" # or messy_ecommerce_sales_data_migrated

# Find exact table name
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
    tables = [r[0] for r in result.fetchall()]
    
    target_table = None
    for t in tables:
        if "messy" in t.lower():
            target_table = t
            break

if target_table:
    print(f"Found table: {target_table}")
    df = pd.read_sql(f'SELECT * FROM "{target_table}" LIMIT 10', engine)
    print("\n--- SAMPLE DATA (First 10 rows) ---")
    print(df.to_string())
else:
    print("Could not find any table with 'messy' in the name.")
    print("Available tables:", tables)
