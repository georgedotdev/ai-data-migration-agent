from connectors.csv_connector import CSVConnector

source = CSVConnector(
    "data/enterprise.csv"
)

df = source.read_data()

print(df.head())

print(
    source.get_schema()
)