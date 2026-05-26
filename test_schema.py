from etl.schema import discover_schema

schema = discover_schema("data/enterprise.csv")

print(schema)