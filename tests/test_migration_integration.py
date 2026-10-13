"""
End-to-end migrations between real databases.

DuckDB and SQLite always run (files in a temp dir). PostgreSQL, MySQL and
MongoDB run when reachable (locally: `docker compose up -d postgres mysql mongodb`;
in CI: service containers) and are skipped otherwise.
"""

import os
import uuid

import pytest
from sqlalchemy import text

from etl.endpoints import Endpoint

CFG = {
    "postgresql": {"host": os.environ.get("PG_HOST", "127.0.0.1"), "port": int(os.environ.get("PG_PORT", 5432)),
                   "database": os.environ.get("PG_DATABASE", "migration_db"),
                   "username": os.environ.get("PG_USER", "postgres"), "password": os.environ.get("PG_PASSWORD", "postgres")},
    "mysql": {"host": os.environ.get("MYSQL_HOST", "127.0.0.1"), "port": int(os.environ.get("MYSQL_PORT", 3306)),
              "database": os.environ.get("MYSQL_DATABASE", "migration_db"),
              "username": os.environ.get("MYSQL_USER", "root"), "password": os.environ.get("MYSQL_PASSWORD", "rootpassword")},
    "mongodb": {"uri": os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"),
                "database": os.environ.get("MONGO_DATABASE", "migration_db")},
}
KINDS = ["postgresql", "mysql", "duckdb", "sqlite", "mongodb"]
PREFIX = "it_"


def _reachable(kind):
    if kind in ("duckdb", "sqlite"):
        return True
    try:
        Endpoint(kind, dict(CFG[kind])).ping()
        return True
    except Exception:
        return False


AVAILABLE = {k: _reachable(k) for k in KINDS}


def needs(*kinds):
    missing = [k for k in kinds if not AVAILABLE[k]]
    return pytest.mark.skipif(bool(missing), reason=f"{', '.join(missing)} not reachable")


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    return tmp_path_factory.mktemp("dbs")


def ep(kind, role, files):
    if kind in ("duckdb", "sqlite"):
        return Endpoint(kind, {"path": str(files / f"{role}.{kind}")})
    return Endpoint(kind, dict(CFG[kind]))


@pytest.fixture(scope="module", autouse=True)
def seeded(files):
    from data.seed_postgres import seed_endpoint
    for k in KINDS:
        if AVAILABLE[k]:
            seed_endpoint(ep(k, "src", files))
    yield
    # drop the it_* tables/collections these tests created
    for k in ("postgresql", "mysql", "mongodb"):
        if not AVAILABLE[k]:
            continue
        e = ep(k, "tgt", files)
        names = [n for n in e.list_tables() if n.startswith(PREFIX)]
        if k == "mongodb":
            for n in names:
                e.mongo().drop_collection(n)
            continue
        with e.engine().connect() as c:
            if k == "mysql":
                c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for n in names:
                c.execute(text(f"DROP TABLE IF EXISTS {e.dialect.q(n)}" + (" CASCADE" if k == "postgresql" else "")))
            if k == "mysql":
                c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            c.commit()


def _assert_verified(res):
    failed = [(c["check"], c["expected"], c["actual"]) for c in res.get("checks", []) if not c["passed"]]
    assert res["status"] == "success", (res.get("message"), failed)


MATRIX = [(s, t) for s in KINDS for t in KINDS]


@pytest.mark.parametrize("src,tgt", MATRIX, ids=[f"{s}->{t}" for s, t in MATRIX])
def test_flat_migration_matrix(src, tgt, files):
    if not (AVAILABLE[src] and AVAILABLE[tgt]):
        pytest.skip("database not reachable")
    from migration_service import run_migration
    res = run_migration("dirty_employees", f"{PREFIX}emp_{src}", source=ep(src, "src", files), target=ep(tgt, "tgt", files))
    _assert_verified(res)
    assert res["source_rows"] == 190 and res["target_rows"] == 177
    # every CHECK/validator probe was rejected by the target itself
    probes = [c for c in res["checks"] if "rejects" in c["check"]]
    assert probes and all(c["passed"] for c in probes)


@pytest.mark.parametrize("tgt", KINDS)
def test_3nf_orders_into_every_target(tgt, files):
    if not AVAILABLE[tgt]:
        pytest.skip(f"{tgt} not reachable")
    from migration_service import run_migration
    res = run_migration("dirty_orders", f"{PREFIX}ord_3nf", normalize_column="product", lookup_table=f"{PREFIX}products",
                        source=ep("sqlite", "src", files), target=ep(tgt, "tgt", files))
    _assert_verified(res)
    assert res["dependents"] == ["category"]
    assert any("orphan" in c["check"] for c in res["checks"])


@pytest.mark.parametrize("tgt", ["postgresql", "mysql", "duckdb", "sqlite"])
def test_rerun_replaces_tables_atomically(tgt, files):
    if not AVAILABLE[tgt]:
        pytest.skip(f"{tgt} not reachable")
    from migration_service import run_migration
    target = ep(tgt, "tgt", files)
    for _ in range(2):
        res = run_migration("dirty_employees", f"{PREFIX}emp_3nf", normalize_column="department",
                            lookup_table=f"{PREFIX}departments", source=ep("duckdb", "src", files), target=target)
        _assert_verified(res)
    leftovers = [n for n in target.list_tables() if n.endswith(("__stg", "__old"))]
    assert leftovers == []


@pytest.mark.parametrize("tgt", ["postgresql", "mysql", "duckdb", "sqlite", "mongodb"])
def test_failed_load_leaves_live_table_untouched(tgt, files, monkeypatch):
    if not AVAILABLE[tgt]:
        pytest.skip(f"{tgt} not reachable")
    import etl.mongo_loader as mongo_loader
    import etl.sql_loader as sql_loader
    from migration_service import run_migration
    target = ep(tgt, "tgt", files)
    name = f"{PREFIX}orders_safe"
    assert run_migration("dirty_orders", name, source=ep("sqlite", "src", files), target=target)["status"] == "success"
    before = target.count(name)

    original = sql_loader.prepare_rows

    def corrupt(td, df, dialect=None):
        rows = original(td, df, dialect)
        if td.name == name:
            i = [c.name for c in td.columns].index("quantity")
            bad = list(rows[-1])
            bad[i] = -10          # violates CHECK (quantity > 0) / validator, at the END of the load
            rows = rows[:-1] + [tuple(bad)]
        return rows

    monkeypatch.setattr(sql_loader, "prepare_rows", corrupt)
    monkeypatch.setattr(mongo_loader, "prepare_rows", corrupt)
    res = run_migration("dirty_orders", name, source=ep("sqlite", "src", files), target=target)
    assert res["status"] == "error" and ("rolled back" in res["message"] or "untouched" in res["message"])
    assert target.count(name) == before


@needs("postgresql", "mysql")
def test_legacy_pg_to_mysql_signature_still_works():
    from migration_service import run_migration
    res = run_migration("dirty_employees", f"{PREFIX}legacy_call", CFG["postgresql"], CFG["mysql"])
    _assert_verified(res)


AGENTIC = [("csv", "sqlite"), ("sqlite", "duckdb"), ("postgresql", "mysql"), ("mongodb", "mongodb")]


@pytest.mark.parametrize("src,tgt", AGENTIC, ids=[f"{s}->{t}" for s, t in AGENTIC])
def test_agentic_workflow_pauses_for_review_then_executes(src, tgt, files):
    """LangGraph flow with the rule-based planner: profile -> plan -> human review -> execute -> reconcile."""
    if not (AVAILABLE.get(src, True) and AVAILABLE[tgt]):
        pytest.skip("database not reachable")
    from migration_service import get_agent_state, resume_migration, start_migration

    def cfg(kind, role, table):
        if kind == "csv":
            return {"file_path": os.path.join(os.path.dirname(__file__), "..", "data", "dirty_employees.csv")}
        if kind in ("duckdb", "sqlite"):
            return {"db_path": str(files / f"{role}.{kind}"), "table_name": table}
        if kind == "mongodb":
            return {"connection_string": CFG["mongodb"]["uri"], "database": CFG["mongodb"]["database"], "collection": table}
        return {**CFG[kind], "table_name": table}

    tid = str(uuid.uuid4())
    start_migration(tid, {
        "query": "clean and migrate", "ai_provider": "Deterministic", "ai_model": "",
        "source_type": src, "target_type": tgt,
        "source_config": cfg(src, "src", "dirty_employees"), "target_config": cfg(tgt, "tgt", f"{PREFIX}ai_emp"),
        "table_name": f"{PREFIX}ai_emp", "plan_approved": False, "executed_steps": [], "timings": {}})
    snap = get_agent_state(tid)
    assert snap.next == ("human_review",)                       # paused for the human
    steps = snap.values["transformation_dsl"]["transformations"]
    assert len(steps) >= 3
    final = resume_migration(tid, plan_approved=True)
    assert final["success"] is True
    assert all(e["status"] == "success" for e in final["execution_log"])
    assert final["reconciliation"]["overall_success"] is True
