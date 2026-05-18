from etl.extract import extract_csv
from etl.load import load_to_duckdb

df = extract_csv("data/enterprise.csv")

load_to_duckdb(df, "migration.duckdb", "enterprise")

print("Data loaded successfully into DuckDB!")