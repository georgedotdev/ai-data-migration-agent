import pandas as pd
import duckdb

csv_df = pd.read_csv('global_freelancers_raw.csv')
print(f'CSV Rows: {len(csv_df)}')

try:
    conn = duckdb.connect('migration (3).duckdb')
    tables = conn.execute('SHOW TABLES').fetchall()
    print('Tables in DuckDB:', tables)
    
    table_name = 'global_freelancers_raw'
    db_df = conn.execute(f'SELECT * FROM "{table_name}"').df()
    print(f'DuckDB Rows: {len(db_df)}')
    
    print('\n--- Columns ---')
    print('CSV Columns:', list(csv_df.columns))
    print('DuckDB Columns:', list(db_df.columns))
    
    print('\n--- Null Counts (CSV) ---')
    print(csv_df.isnull().sum().to_dict())
    print('\n--- Null Counts (DuckDB) ---')
    print(db_df.isnull().sum().to_dict())
except Exception as e:
    print('DuckDB Error:', e)
