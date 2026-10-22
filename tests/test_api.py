"""
REST API tests (in-process, no server needed). Uses CSV/DuckDB/SQLite so they
always run; the database matrix is covered by test_migration_integration.py.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def test_config_lists_systems_presets_and_hides_passwords():
    r = client.get("/api/config")
    assert r.status_code == 200
    cfg = r.json()
    assert {s["kind"] for s in cfg["systems"]} == {"postgresql", "mysql", "duckdb", "sqlite", "mongodb", "csv"}
    assert [p["id"] for p in cfg["presets"]] == ["dirty_employees", "dirty_orders"]
    assert cfg["presets"][0]["defect_total"] > 0
    assert all("password" not in s["defaults"] for s in cfg["systems"])
    assert {p["name"] for p in cfg["ai"]["providers"]} == {"Gemini", "Groq", "OpenAI"}


def test_health_reports_every_system():
    h = client.get("/api/health").json()
    assert set(h["systems"]) == {"postgresql", "mysql", "mongodb", "duckdb", "sqlite"}
    assert h["systems"]["sqlite"]["ok"] and h["systems"]["duckdb"]["ok"]


def test_seed_then_migrate_sqlite_to_duckdb_with_proof_queries_and_export():
    src = {"kind": "sqlite", "config": {"file": "api_test_src.sqlite"}, "table": "dirty_orders"}
    assert client.post("/api/seed", json={"endpoint": src, "tables": ["dirty_orders"]}).json()["seeded"] == {"dirty_orders": 248}
    r = client.post("/api/migrate", json={
        "source": src, "target": {"kind": "duckdb", "config": {"file": "api_test_tgt.duckdb"}, "table": "orders"},
        "normalize_column": "product", "lookup_table": "products"}).json()
    assert r["status"] == "success", [c for c in r["checks"] if not c["passed"]]
    assert r["stats"]["loaded_rows"] == 238 and r["dependents"] == ["category"]
    assert set(r["target_info"]) == {"orders", "products"}
    for q in r["queries"]:
        out = client.post(f"/api/migrations/{r['result_id']}/query", json={"name": q["name"]})
        assert out.status_code == 200 and out.json()["columns"]
    csv = client.get(f"/api/migrations/{r['result_id']}/export.csv")
    assert csv.status_code == 200 and len(csv.text.strip().splitlines()) == 239   # header + every row, not just 50
    json.dumps(r)   # fully JSON-serializable


def test_upload_csv_and_migrate_keeps_original_filename():
    with open(os.path.join(DATA, "dirty_employees.csv"), "rb") as f:
        up = client.post("/api/upload", files={"file": ("my data (1).csv", f, "text/csv")}).json()
    r = client.post("/api/migrate", json={
        "source": {"kind": "csv", "config": {"upload_id": up["upload_id"]}},
        "target": {"kind": "sqlite", "config": {"file": "api_test_tgt.sqlite"}, "table": "employees"}}).json()
    assert r["status"] == "success"
    assert r["source_table"] == "my_data__1_.csv"


def test_rejects_non_csv_upload():
    r = client.post("/api/upload", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


@pytest.mark.parametrize("cfg", [{"upload_id": "../../etc/passwd"}, {"upload_id": "0" * 32}])
def test_csv_upload_ids_cannot_escape(cfg):
    r = client.post("/api/migrate", json={"source": {"kind": "csv", "config": cfg},
                                          "target": {"kind": "sqlite", "config": {}, "table": "x"}})
    assert r.status_code in (400, 404)


def test_database_files_are_confined_to_runtime_dir():
    from etl.endpoints import RUNTIME_DIR
    from api.main import EndpointSpec, resolve_endpoint
    ep = resolve_endpoint(EndpointSpec(kind="sqlite", config={"file": "../../evil.sqlite"}), "target")
    assert os.path.dirname(ep.config["path"]) == RUNTIME_DIR
    with pytest.raises(Exception):
        resolve_endpoint(EndpointSpec(kind="sqlite", config={"file": "evil.exe"}), "target")


def test_csv_cannot_be_a_target():
    r = client.post("/api/migrate", json={"source": {"kind": "csv", "config": {}},
                                          "target": {"kind": "csv", "config": {}, "table": "x"}})
    assert r.status_code == 400


def test_agent_workflow_pause_review_execute_and_download():
    a = client.post("/api/agent/start", json={
        "source": {"kind": "csv", "config": {"preset": "dirty_employees"}},
        "target": {"kind": "sqlite", "config": {"file": "api_test_agent.sqlite"}, "table": "employees_ai"},
        "provider": "Deterministic"}).json()
    assert a["status"] == "paused" and a["next"] == ["human_review"]
    assert "source_config" not in a["state"] and "target_config" not in a["state"]   # no credentials to the browser
    steps = a["state"]["transformation_dsl"]["transformations"]
    assert len(steps) >= 3
    f = client.post(f"/api/agent/{a['thread_id']}/resume", json={"approved": True, "rejected_steps": [len(steps) - 1]}).json()
    assert f["status"] == "finished" and f["state"]["success"] is True
    assert len(f["state"]["execution_log"]) == len(steps) - 1          # rejected step was not executed
    assert f["state"]["database_download"] is True
    assert client.get(f"/api/agent/{a['thread_id']}/database").status_code == 200


def test_unknown_agent_thread_is_404():
    assert client.get("/api/agent/does-not-exist").status_code == 404
