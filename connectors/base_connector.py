from abc import ABC, abstractmethod


class BaseConnector(ABC):

    @abstractmethod
    def read_data(self):
        pass

    @abstractmethod
    def write_data(self, df):
        pass

    @abstractmethod
    def get_schema(self):
        pass