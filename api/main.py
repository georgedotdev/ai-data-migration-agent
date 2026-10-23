"""
REST API for the AI Data Migration Agent.

Wraps the existing, tested pipeline:
  * migration_service.run_migration  - deterministic migration between any two systems
  * migration_service.start/resume   - LangGraph agentic workflow (LLM plan -> human review -> execute)

Security notes
  * Database passwords never leave the server: /api/config only reports whether one is set,
    and blank fields in requests mean "use the server's configured value".
  * DuckDB/SQLite files are confined to RUNTIME_DIR; uploaded CSVs are referenced by id, not path.
  * LLM API keys typed in the UI are sent per request and never stored server-side.

Run:  uvicorn api.main:app --reload --port 8000
"""

import json
import os
import re
import sys
import tempfile
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from ai_brain import DEFAULT_MODELS, MODEL_OPTIONS, PROVIDER_ENV_KEYS  # noqa: E402
from api.serialize import jsonable, table  # noqa: E402
from etl import mongo_loader, sql_loader  # noqa: E402
from etl.endpoints import LABELS, RUNTIME_DIR, SOURCE_KINDS, TARGET_KINDS, Endpoint, default_config  # noqa: E402
import migration_service  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "ai_migration_uploads")
WEB_DIST = os.path.join(ROOT, "web", "dist")
FILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.(duckdb|sqlite|db)$")

PRESETS = [
    {"id": "dirty_employees", "label": "HR employees", "csv": "dirty_employees.csv", "target": "employees",
     "normalize_column": "department", "lookup_table": "departments",
     "blurb": "Salaries as $/k/USD text, ages like 999, broken emails, misspelled departments, duplicate IDs"},
    {"id": "dirty_orders", "label": "Retail orders", "csv": "dirty_orders.csv", "target": "orders",
     "normalize_column": "product", "lookup_table": "products",
     "blurb": "Currency prefixes, 15%/0.15 discounts, invalid quantities, payment-method variants, missing order IDs"},
]

app = FastAPI(title="AI Data Migration Agent", version="2.0")


# ─────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────

class EndpointSpec(BaseModel):
    kind: str
    config: dict = Field(default_factory=dict)
    table: str | None = None


class MigrateRequest(BaseModel):
    source: EndpointSpec
    target: EndpointSpec
    normalize_column: str | None = None
    lookup_table: str | None = None


class SeedRequest(BaseModel):
    endpoint: EndpointSpec
    tables: list[str] | None = None


class QueryRequest(BaseModel):
    name: str


class AgentStart(BaseModel):
    source: EndpointSpec
    target: EndpointSpec
    provider: str = "Auto"
    model: str = ""
    goal: str = ""
    api_keys: dict = Field(default_factory=dict)


class AgentResume(BaseModel):
    approved: bool
    feedback: str = ""
    rejected_steps: list[int] = Field(default_factory=list)
    api_keys: dict = Field(default_factory=dict)


# ─────────────────────────────────────────────
# Endpoint resolution
# ─────────────────────────────────────────────

def _uploads():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    return UPLOAD_DIR


def resolve_endpoint(spec: EndpointSpec, role: str) -> Endpoint:
    kind = spec.kind
    allowed = SOURCE_KINDS if role == "source" else TARGET_KINDS
    if kind not in allowed:
        raise HTTPException(400, f"{kind!r} cannot be a {role}")
    cfg = default_config(kind, role)
    given = {k: v for k, v in (spec.config or {}).items() if v not in (None, "")}

    if kind in ("postgresql", "mysql"):
        for k in ("host", "port", "database", "username", "password"):
            if k in given:
                cfg[k] = int(given[k]) if k == "port" else str(given[k])
    elif kind == "mongodb":
        for k in ("uri", "database"):
            if k in given:
                cfg[k] = str(given[k])
    elif kind in ("duckdb", "sqlite"):
        name = os.path.basename(str(given.get("file") or os.path.basename(cfg["path"])))
        if not FILE_RE.match(name):
            raise HTTPException(400, f"Invalid database file name {name!r}")
        cfg = {"path": os.path.join(RUNTIME_DIR, name)}
    elif kind == "csv":
        if given.get("upload_id"):
            uid = str(given["upload_id"])
            if not re.fullmatch(r"[0-9a-f]{32}", uid):
                raise HTTPException(400, "Invalid upload id")
            matches = [f for f in os.listdir(_uploads()) if f.startswith(uid + "_")]
            if not matches:
                raise HTTPException(404, "Upload not found; please upload the CSV again")
            cfg = {"path": os.path.join(_uploads(), matches[0])}
        else:
            preset = next((p for p in PRESETS if p["id"] == given.get("preset")), PRESETS[0])
            cfg = {"path": os.path.join(DATA_DIR, preset["csv"])}
    return Endpoint(kind, cfg)


def connector_kwargs(spec: EndpointSpec, role: str) -> tuple[str, dict]:
    """Translate an endpoint into the kwargs the agentic workflow's connectors expect."""
    ep = resolve_endpoint(spec, role)
    table_name = spec.table or ""
    c = ep.config
    if ep.kind == "csv":
        return "csv", {"file_path": c["path"]}
    if ep.kind in ("postgresql", "mysql"):
        return ep.kind, {**{k: c[k] for k in ("host", "port", "database", "username", "password")}, "table_name": table_name}
    if ep.kind in ("duckdb", "sqlite"):
        return ep.kind, {"db_path": c["path"], "table_name": table_name}
    return "mongodb", {"connection_string": c["uri"], "database": c["database"], "collection": table_name}


def _err(e: Exception) -> str:
    return str(getattr(e, "orig", e)).split("\n")[0][:400]


# ─────────────────────────────────────────────
# Config & health
# ─────────────────────────────────────────────

def _manifest():
    try:
        with open(os.path.join(DATA_DIR, "dirty_data_manifest.json"), encoding="utf-8") as f:
            return json.load(f)["datasets"]
    except (OSError, ValueError, KeyError):
        return {}


@app.get("/api/config")
def config():
    manifest = _manifest()
    presets = []
    for p in PRESETS:
        ds = manifest.get(p["id"], {})
        defects = [{"defect": k.replace("_", " "), "count": v["count"],
                    "example": "; ".join(str(e["detail"]) for e in v["examples"][:2])}
                   for k, v in sorted(ds.get("defects", {}).items(), key=lambda kv: -kv[1]["count"])]
        presets.append({**p, "rows": ds.get("rows"), "defects": defects,
                        "defect_total": sum(d["count"] for d in defects)})
    systems = []
    for k in SOURCE_KINDS:
        d = default_config(k, "source")
        public = {kk: vv for kk, vv in d.items() if kk != "password"}
        if "path" in public:
            public = {"file": os.path.basename(public.pop("path"))}
        if k == "csv":
            public = {}
        systems.append({"kind": k, "label": LABELS[k], "source": k in SOURCE_KINDS, "target": k in TARGET_KINDS,
                        "defaults": public, "password_set": bool(d.get("password"))})
    for s in systems:
        if s["kind"] in ("duckdb", "sqlite"):
            s["target_defaults"] = {"file": f"target.{s['kind']}"}
    return {
        "presets": presets,
        "systems": systems,
        "ai": {"providers": [{"name": p, "models": MODEL_OPTIONS.get(p, []), "default_model": DEFAULT_MODELS.get(p),
                              "server_key": any(os.environ.get(k) for k in PROVIDER_ENV_KEYS[p])}
                             for p in ("Gemini", "Groq", "OpenAI")]},
    }


@app.get("/api/health")
def health():
    def ping(kind):
        try:
            return kind, {"ok": True, "detail": Endpoint(kind, default_config(kind, "source")).ping()}
        except Exception as e:
            return kind, {"ok": False, "detail": _err(e)}
    with ThreadPoolExecutor(5) as pool:
        systems = dict(pool.map(ping, ["postgresql", "mysql", "mongodb", "duckdb", "sqlite"]))
    ai = {p: any(os.environ.get(k) for k in PROVIDER_ENV_KEYS[p]) for p in ("Gemini", "Groq", "OpenAI")}
    return {"systems": systems, "ai": ai}


# ─────────────────────────────────────────────
# Endpoint utilities
# ─────────────────────────────────────────────

@app.post("/api/test")
def test_endpoint(spec: EndpointSpec, role: str = "source"):
    try:
        ep = resolve_endpoint(spec, role)
        return {"ok": True, "message": ep.ping()}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "message": _err(e)}


@app.post("/api/tables")
def list_tables(spec: EndpointSpec, role: str = "source"):
    try:
        return {"tables": resolve_endpoint(spec, role).list_tables()}
    except HTTPException:
        raise
    except Exception as e:
        return {"tables": [], "error": _err(e)}


@app.post("/api/seed")
def seed(req: SeedRequest):
    from data.seed_postgres import seed_endpoint
    ep = resolve_endpoint(req.endpoint, "source")
    if ep.kind == "csv":
        raise HTTPException(400, "CSV sources don't need seeding")
    try:
        return {"seeded": seed_endpoint(ep, req.tables)}
    except Exception as e:
        raise HTTPException(500, f"Could not seed {ep.label}: {_err(e)}")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")
    uid = uuid.uuid4().hex
    path = os.path.join(_uploads(), f"{uid}_{re.sub(r'[^A-Za-z0-9_.-]', '_', os.path.basename(file.filename))}")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(413, "CSV larger than 200 MB")
    with open(path, "wb") as f:
        f.write(data)
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=5000)
    except Exception as e:
        os.remove(path)
        raise HTTPException(400, f"Could not read CSV: {_err(e)}")
    return {"upload_id": uid, "filename": file.filename, "columns": list(df.columns),
            "preview": table(df, 5)}


# ─────────────────────────────────────────────
# Deterministic migration
# ─────────────────────────────────────────────

_RESULTS: "OrderedDict[str, tuple[dict, Endpoint]]" = OrderedDict()
_LOCK = threading.Lock()


def _remember(res, target):
    rid = uuid.uuid4().hex
    with _LOCK:
        _RESULTS[rid] = (res, target)
        while len(_RESULTS) > 30:
            _RESULTS.popitem(last=False)
    return rid


def _result(rid):
    with _LOCK:
        if rid not in _RESULTS:
            raise HTTPException(404, "Result expired; run the migration again")
        return _RESULTS[rid]


@app.post("/api/migrate")
def migrate(req: MigrateRequest):
    source = resolve_endpoint(req.source, "source")
    target = resolve_endpoint(req.target, "target")
    source_table = req.source.table or ""
    if source.kind == "csv":   # show the original file name, not the stored upload name
        source_table = re.sub(r"^[0-9a-f]{32}_", "", os.path.basename(source.config["path"]))
    res = migration_service.run_migration(
        source_table=source_table, target_table=(req.target.table or "").strip(),
        normalize_column=req.normalize_column or None, lookup_table=req.lookup_table or None,
        source=source, target=target)
    if res.get("status") == "error":
        return {"status": "error", "message": res.get("message"),
                "transformation_log": jsonable(res.get("transformation_log"))}
    loader = mongo_loader if target.kind == "mongodb" else sql_loader
    rid = _remember(res, target)
    out = {k: jsonable(v) for k, v in res.items()
           if k not in ("target_info", "source_preview", "target_preview", "type_mapping", "quarantine", "history")}
    out.update(
        result_id=rid,
        source_preview=table(res["source_preview"].astype(str)),
        target_preview=table(res["target_preview"]),
        type_mapping=table(res["type_mapping"]),
        quarantine=table(res["quarantine"]),
        history=table(res["history"]),
        target_info={t: {"ddl": m["ddl"], "ddl_source": m["ddl_source"], "columns": table(m["columns"]),
                         "constraints": table(m["constraints"])} for t, m in res["target_info"].items()},
        queries=[{"name": n, "text": q if isinstance(q, str) else json.dumps(q, default=str)}
                 for n, q in loader.live_queries(target, res).items()],
    )
    return out


@app.post("/api/migrations/{rid}/query")
def run_live_query(rid: str, req: QueryRequest):
    res, target = _result(rid)
    loader = mongo_loader if target.kind == "mongodb" else sql_loader
    queries = loader.live_queries(target, res)
    if req.name not in queries:
        raise HTTPException(404, "Unknown query")
    try:
        return table(loader.run_query(target, queries[req.name]), 500)
    except Exception as e:
        raise HTTPException(500, f"Query failed: {_err(e)}")


@app.get("/api/migrations/{rid}/export.csv")
def export_csv(rid: str):
    res, target = _result(rid)
    loader = mongo_loader if target.kind == "mongodb" else sql_loader
    spec = loader.live_queries(target, res)[next(iter(loader.live_queries(target, res)))]
    df = (loader.run_query(target, spec.replace(" LIMIT 50", "")) if isinstance(spec, str)
          else loader.run_query(target, spec, limit=None))
    return Response(df.to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{res["target_table"]}.csv"'})


@app.post("/api/history")
def history(spec: EndpointSpec):
    target = resolve_endpoint(spec, "target")
    loader = mongo_loader if target.kind == "mongodb" else sql_loader
    try:
        return table(loader.run_history(target, 50))
    except Exception as e:
        return {"columns": [], "rows": [], "error": f"No migration history in {target.label} yet ({_err(e)})"}


# ─────────────────────────────────────────────
# Agentic workflow
# ─────────────────────────────────────────────

AGENT_KEYS = ["profile", "assessment", "transformation_dsl", "preview", "preview_impact", "risk", "executed_steps",
              "timings", "target_schema", "reconciliation", "report", "execution_log", "quarantine_report", "execution_impact",
              "provider_used", "model_used", "fallback_used", "raw_prompt", "raw_ai_response", "success",
              "source_type", "target_type", "table_name", "human_feedback"]
_AGENT_TARGETS: dict[str, dict] = {}


def _agent_view(tid):
    snap = migration_service.get_agent_state(tid)
    if snap is None or not snap.values:
        raise HTTPException(404, "Unknown or expired workflow")
    nxt = list(snap.next)
    status = "paused" if "human_review" in nxt else ("finished" if not nxt else "running")
    values = {k: jsonable(snap.values.get(k)) for k in AGENT_KEYS}
    tgt = _AGENT_TARGETS.get(tid, {})
    values["database_download"] = bool(
        status == "finished" and tgt.get("kind") in ("duckdb", "sqlite") and os.path.exists(tgt.get("path", "")))
    return {"thread_id": tid, "status": status, "next": nxt, "state": values}


@app.post("/api/agent/start")
def agent_start(req: AgentStart):
    src_type, src_cfg = connector_kwargs(req.source, "source")
    tgt_type, tgt_cfg = connector_kwargs(req.target, "target")
    if not req.target.table:
        raise HTTPException(400, "Target table/collection name is required")
    tid = str(uuid.uuid4())
    _AGENT_TARGETS[tid] = {"kind": tgt_type, "path": tgt_cfg.get("db_path", "")}
    state = {"query": req.goal or "Clean this dataset and migrate it", "ai_provider": req.provider,
             "ai_model": req.model, "source_type": src_type, "target_type": tgt_type,
             "source_config": src_cfg, "target_config": tgt_cfg, "table_name": req.target.table,
             "plan_approved": False, "executed_steps": [], "timings": {}}
    try:
        migration_service.start_migration(tid, state, api_keys={k: v for k, v in req.api_keys.items() if v})
    except Exception as e:
        raise HTTPException(500, f"Workflow failed: {_err(e)}")
    return _agent_view(tid)


@app.post("/api/agent/{tid}/resume")
def agent_resume(tid: str, req: AgentResume):
    _agent_view(tid)   # 404 if unknown
    try:
        migration_service.resume_migration(tid, plan_approved=req.approved, human_feedback=req.feedback,
                                           rejected_steps=req.rejected_steps,
                                           api_keys={k: v for k, v in req.api_keys.items() if v})
    except Exception as e:
        raise HTTPException(500, f"Workflow failed: {_err(e)}")
    return _agent_view(tid)


@app.get("/api/agent/{tid}")
def agent_get(tid: str):
    return _agent_view(tid)


@app.get("/api/agent/{tid}/database")
def agent_database(tid: str):
    tgt = _AGENT_TARGETS.get(tid)
    if not tgt or tgt["kind"] not in ("duckdb", "sqlite") or not os.path.exists(tgt["path"]):
        raise HTTPException(404, "No database file for this workflow")
    return FileResponse(tgt["path"], filename=os.path.basename(tgt["path"]), media_type="application/octet-stream")


# ─────────────────────────────────────────────
# Frontend (built React app)
# ─────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled(_request, exc):
    return JSONResponse(status_code=500, content={"detail": f"Server error: {_err(exc)}"})


if os.path.isdir(os.path.join(WEB_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    candidate = os.path.join(WEB_DIST, path)
    if path and os.path.isfile(candidate) and os.path.commonpath([candidate, WEB_DIST]) == WEB_DIST:
        return FileResponse(candidate)
    index = os.path.join(WEB_DIST, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend not built. Run: cd web && npm install && npm run build"}, status_code=503)
