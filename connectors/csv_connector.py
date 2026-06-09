import pandas as pd

from connectors.base_connector import BaseConnector


class CSVConnector(BaseConnector):

    def __init__(self, file_path):

        self.file_path = file_path

    def _read_with_fallback(self):
        encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin1', 'iso-8859-1']
        for enc in encodings:
            try:
                return pd.read_csv(self.file_path, encoding=enc)
            except UnicodeDecodeError:
                continue
        # Fallback to default behavior if all fail
        return pd.read_csv(self.file_path, encoding='utf-8', errors='replace')

    def read_data(self):
        return self._read_with_fallback()

    def write_data(self, df):
        df.to_csv(
            self.file_path,
            index=False
        )

    def get_schema(self):
        df = self._read_with_fallback()
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
        df = self._read_with_fallback()
        return len(df)