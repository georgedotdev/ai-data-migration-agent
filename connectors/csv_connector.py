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