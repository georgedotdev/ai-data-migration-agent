from connectors.csv_connector import CSVConnector
from connectors.duckdb_connector import DuckDBConnector

source = CSVConnector(
    "data/enterprise.csv"
)

target = DuckDBConnector(
    "migration.duckdb",
    "connector_test"
)

df = source.read_data()

target.write_data(df)

loaded_df = target.read_data()

print(loaded_df.head())

print(
    f"Rows loaded: {len(loaded_df)}"
)