"""
End-to-end PostgreSQL -> MySQL migration against real databases.

Runs when both databases from docker-compose.yml are reachable (locally via
`docker compose up -d`, in CI via service containers); skipped otherwise.
"""

import os

import pytest
from sqlalchemy import text

PG = {"host": os.environ.get("PG_HOST", "127.0.0.1"), "port": int(os.environ.get("PG_PORT", 5432)),
      "database": os.environ.get("PG_DATABASE", "migration_db"), "username": os.environ.get("PG_USER", "postgres"),
      "password": os.environ.get("PG_PASSWORD", "postgres")}
MY = {"host": os.environ.get("MYSQL_HOST", "127.0.0.1"), "port": int(os.environ.get("MYSQL_PORT", 3306)),
      "database": os.environ.get("MYSQL_DATABASE", "migration_db"), "username": os.environ.get("MYSQL_USER", "root"),
      "password": os.environ.get("MYSQL_PASSWORD", "rootpassword")}


def _reachable():
    try:
        from connectors.mysql_connector import MySQLConnector
        from connectors.postgres_connector import PostgreSQLConnector
        with PostgreSQLConnector(**PG).engine.connect() as c:
            c.execute(text("SELECT 1"))
        with MySQLConnector(**MY).engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="PostgreSQL/MySQL not reachable (run docker compose up -d)")


@pytest.fixture(scope="module", autouse=True)
def seeded():
    from data.seed_postgres import seed_postgres
    yield seed_postgres(PG)
    # drop the it_* tables these tests created (FK checks off so order doesn't matter)
    with _engine().connect() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'it\_%'"))]
        c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for n in names:
            c.execute(text(f"DROP TABLE `{n}`"))
        c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        c.commit()


def _engine():
    from connectors.mysql_connector import MySQLConnector
    return MySQLConnector(**MY).engine


@pytest.mark.parametrize("source,target", [("dirty_employees", "it_employees"), ("dirty_orders", "it_orders")])
def test_flat_migration_is_verified(source, target):
    from migration_service import run_migration
    res = run_migration(source, target, PG, MY)
    failed = [c for c in res.get("checks", []) if not c["passed"]]
    assert res["status"] == "success", (res.get("message"), failed)
    with _engine().connect() as c:
        assert c.execute(text(f"SELECT COUNT(*) FROM `{target}`")).scalar() == res["target_rows"]
        run = c.execute(text("SELECT status, source_rows, loaded_rows FROM migration_runs WHERE run_id = :r"),
                        {"r": res["run_id"]}).fetchone()
    assert run == ("success", res["source_rows"], res["target_rows"])


def test_normalized_migration_has_fk_and_rerun_swaps_atomically():
    from migration_service import run_migration
    for _ in range(2):   # second run exercises the RENAME swap over existing tables
        res = run_migration("dirty_employees", "it_emp_3nf", PG, MY,
                            normalize_column="department", lookup_table="it_departments")
        assert res["status"] == "success", [c for c in res["checks"] if not c["passed"]]
    with _engine().connect() as c:
        fk = c.execute(text("""
            SELECT REFERENCED_TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'it_emp_3nf' AND REFERENCED_TABLE_NAME IS NOT NULL
        """)).scalar()
        leftovers = c.execute(text("""
            SELECT COUNT(*) FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND (TABLE_NAME LIKE '%\\_\\_stg' OR TABLE_NAME LIKE '%\\_\\_old')
        """)).scalar()
    assert fk == "it_departments"
    assert leftovers == 0
    assert res["explain"]["after"][0]["key"] == "idx_join_date"


def test_failed_load_leaves_live_table_untouched(monkeypatch):
    from migration_service import run_migration
    import etl.mysql_loader as loader
    assert run_migration("dirty_orders", "it_orders_safe", PG, MY)["status"] == "success"
    with _engine().connect() as c:
        before = c.execute(text("SELECT COUNT(*) FROM `it_orders_safe`")).scalar()

    original = loader.prepare_rows

    def corrupt(td, df):
        rows = original(td, df)
        idx = [c.name for c in td.columns].index("quantity")
        bad = list(rows[0])
        bad[idx] = -10          # violates CHECK (quantity > 0) mid-load
        return [tuple(bad)] + rows[1:]

    monkeypatch.setattr(loader, "prepare_rows", corrupt)
    res = run_migration("dirty_orders", "it_orders_safe", PG, MY)
    assert res["status"] == "error" and "rolled back" in res["message"]
    with _engine().connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM `it_orders_safe`")).scalar() == before
        assert c.execute(text("SELECT status FROM migration_runs ORDER BY run_id DESC LIMIT 1")).scalar() == "failed"


def test_orders_3nf_moves_category_into_products():
    from migration_service import run_migration
    res = run_migration("dirty_orders", "it_orders_3nf", PG, MY, normalize_column="product", lookup_table="it_products")
    assert res["status"] == "success", [c for c in res["checks"] if not c["passed"]]
    assert res["dependents"] == ["category"]
    with _engine().connect() as c:
        cols = [r[0] for r in c.execute(text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'it_products'"))]
        n = c.execute(text("SELECT COUNT(*) FROM it_orders_3nf o JOIN it_products p ON o.product_id = p.id")).scalar()
    assert set(cols) == {"id", "product", "category"}
    assert n == res["target_rows"]
