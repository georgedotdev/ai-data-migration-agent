import pandas as pd
from etl.dsl_engine import execute_dsl

df = pd.read_csv('csv_files/adversarial_lineage.csv')

dsl = {
    "transformations": [
        {"action": "normalize_columns"},
        {"action": "parse_currency", "column": "Hourly Rate (USD)"},
        {"action": "fill_missing", "column": "Hourly Rate (USD)", "strategy": "constant", "value": 0.0},
        {"action": "cast_type", "column": "Hourly Rate (USD)", "target_type": "float64"},
        {"action": "standardize_boolean", "column": "Active?"}
    ]
}

# Execute
df_out, log, quarantine = execute_dsl(df, dsl)

for step in log:
    print(step)

print("--- Data output ---")
print(df_out.to_dict(orient="records"))
