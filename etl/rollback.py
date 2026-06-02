import duckdb


def rollback_migration(
    db_path: str,
    table_name: str
):

    conn = duckdb.connect(db_path)

    conn.execute(
        f"DROP TABLE IF EXISTS {table_name}"
    )

    conn.close()

    print(f"[ROLLBACK] Removed table {table_name}")