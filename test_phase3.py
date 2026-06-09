import os
import pandas as pd
from connectors.connector_factory import get_connector

os.makedirs('csv_files/encoding_tests', exist_ok=True)

data_utf8 = {
    'Name': ['José', 'François', 'Müller'],
    'Value': ['€100', '£50', '₹500'],
    'Description': ['“Smart Quotes”', 'café', 'naïve']
}
data_cp1252 = {
    'Name': ['José', 'François', 'Müller'],
    'Value': ['€100', '£50', '$500'],
    'Description': ['“Smart Quotes”', 'café', 'naïve']
}
data_latin1 = {
    'Name': ['José', 'François', 'Müller'],
    'Value': ['$100', '£50', '¥500'],
    'Description': ['"Normal Quotes"', 'café', 'naïve']
}

# Create 4 files with different encodings
files = {
    'utf8': ('csv_files/encoding_tests/test_utf8.csv', 'utf-8', data_utf8),
    'utf8_sig': ('csv_files/encoding_tests/test_utf8_sig.csv', 'utf-8-sig', data_utf8),
    'cp1252': ('csv_files/encoding_tests/test_cp1252.csv', 'cp1252', data_cp1252),
    'latin1': ('csv_files/encoding_tests/test_latin1.csv', 'latin1', data_latin1)
}

for key, (path, enc, dat) in files.items():
    try:
        pd.DataFrame(dat).to_csv(path, index=False, encoding=enc)
        print(f"Created {key} file at {path}")
    except Exception as e:
        print(f"Failed to create {key} file: {e}")

# Test reading with CsvConnector
print("\n--- Testing Connector ---")
for key, (path, enc, dat) in files.items():
    print(f"\nReading {key}...")
    try:
        conn = get_connector('csv', file_path=path)
        df_read = conn.read_data()
        print(f"Success! Read {len(df_read)} rows.")
        print(df_read.head(1))
    except Exception as e:
        print(f"FAILED to read {key}: {type(e).__name__} - {e}")
