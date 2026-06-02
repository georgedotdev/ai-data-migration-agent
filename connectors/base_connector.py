from abc import ABC, abstractmethod


class BaseConnector(ABC):

    @abstractmethod
    def read_data(self):
        """Read all data into a Pandas DataFrame."""
        pass

    @abstractmethod
    def write_data(self, df):
        """Write a Pandas DataFrame to the target."""
        pass

    @abstractmethod
    def get_schema(self):
        """Retrieve schema information."""
        pass

    @abstractmethod
    def drop_table(self):
        """Remove table/collection — used for rollback."""
        pass

    @abstractmethod
    def count_rows(self) -> int:
        """Return row count — used for validation."""
        pass