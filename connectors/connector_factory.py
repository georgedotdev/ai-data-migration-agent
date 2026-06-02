"""
Connector Factory

Central registry for all connectors. Returns the correct
connector instance based on type string.

Usage:
    from connectors.connector_factory import get_connector

    source = get_connector("csv", file_path="data/enterprise.csv")
    target = get_connector("duckdb", db_path="migration.duckdb", table_name="enterprise")
    target = get_connector("postgresql", host="localhost", port=5432, ...)
    target = get_connector("mongodb", connection_string="mongodb://localhost:27017", ...)
"""

from connectors.csv_connector import CSVConnector
from connectors.duckdb_connector import DuckDBConnector
from connectors.postgres_connector import PostgreSQLConnector
from connectors.mongodb_connector import MongoDBConnector


CONNECTOR_REGISTRY = {
    "csv": CSVConnector,
    "duckdb": DuckDBConnector,
    "postgresql": PostgreSQLConnector,
    "mongodb": MongoDBConnector,
}


def get_connector(connector_type, **kwargs):
    """
    Return the correct connector instance based on type string.

    Args:
        connector_type: One of 'csv', 'duckdb', 'postgresql', 'mongodb'
        **kwargs: Connection parameters for the connector

    Returns:
        BaseConnector instance

    Raises:
        ValueError: If connector_type is not registered
    """

    connector_type = connector_type.lower().strip()

    if connector_type not in CONNECTOR_REGISTRY:
        raise ValueError(
            f"Unknown connector type: '{connector_type}'. "
            f"Available: {list(CONNECTOR_REGISTRY.keys())}"
        )

    connector_class = CONNECTOR_REGISTRY[connector_type]

    return connector_class(**kwargs)


def list_connectors():
    """Return list of available connector types."""
    return list(CONNECTOR_REGISTRY.keys())
