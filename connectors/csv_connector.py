import pandas as pd

from connectors.base_connector import BaseConnector


class CSVConnector(BaseConnector):

    def __init__(self, file_path):

        self.file_path = file_path

    def read_data(self):

        return pd.read_csv(self.file_path)

    def write_data(self, df):

        df.to_csv(
            self.file_path,
            index=False
        )

    def get_schema(self):

        df = pd.read_csv(self.file_path)

        return {
            "columns": list(df.columns),
            "row_count": len(df)
        }

    def drop_table(self):
        """No-op — CSV source files should not be deleted."""
        print(
            f"[CSV] drop_table is a no-op for {self.file_path}"
        )

    def count_rows(self):
        """Return row count by reading the CSV."""
        df = pd.read_csv(self.file_path)
        return len(df)