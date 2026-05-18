from etl.extract import extract_csv

df = extract_csv("data/enterprise.csv")
print(df.head())
print(f"Rows: {len(df)}")
print(f"Columns: {len(df.columns)}")