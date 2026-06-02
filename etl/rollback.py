"""
Rollback Module

Connector-generic rollback. Uses target connector's drop_table()
instead of hardcoded DuckDB calls.
"""


def rollback_migration(target_connector):
    """
    Remove the migrated table/collection using the target connector.

    Works for any connector: DuckDB, PostgreSQL, MongoDB.
    """

    target_connector.drop_table()
    print("[ROLLBACK] Migration rolled back")