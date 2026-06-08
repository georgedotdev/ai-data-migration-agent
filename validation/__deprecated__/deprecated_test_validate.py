from etl.validate import validate_migration

is_valid = validate_migration(
    "data/enterprise.csv",
    "migration.duckdb",
    "enterprise"
)

print(f"Validation Result: {is_valid}")