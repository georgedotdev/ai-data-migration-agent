"""
Streamlit UI for the deterministic migration: any source -> any target among
PostgreSQL, MySQL, DuckDB, SQLite and MongoDB (CSV upload as an extra source).

Everything shown under "Proof" is queried live from the systems, not taken
from the pipeline's own bookkeeping.
"""

import json
import os
import tempfile
import uuid

import pandas as pd
import streamlit as st

from etl import mongo_loader, sql_loader
from etl.endpoints import LABELS, SOURCE_KINDS, TARGET_KINDS, Endpoint, default_config
from migration_service import run_migration

ROOT = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(ROOT, "data", "dirty_data_manifest.json")

PRESETS = {
    "👥 HR employees (dirty_employees)": {
        "source": "dirty_employees", "csv": "dirty_employees.csv", "target": "employees",
        "normalize_column": "department", "lookup_table": "departments",
    },
    "🛒 Retail orders (dirty_orders)": {
        "source": "dirty_orders", "csv": "dirty_orders.csv", "target": "orders",
        "normalize_column": "product", "lookup_table": "products",
    },
}
ICONS = {"postgresql": "🐘", "mysql": "🐬", "duckdb": "🦆", "sqlite": "🪶", "mongodb": "🍃", "csv": "📄"}


def _config_inputs(kind, role):
    """Connection widgets for one endpoint; returns its config dict."""
    d = default_config(kind, role)
    k = f"{role}_{kind}"
    if kind in ("postgresql", "mysql"):
        return {
            "host": st.text_input("Host", d["host"], key=f"{k}_h"),
            "port": int(st.number_input("Port", value=int(d["port"]), key=f"{k}_p")),
            "database": st.text_input("Database", d["database"], key=f"{k}_d"),
            "username": st.text_input("User", d["username"], key=f"{k}_u"),
            "password": st.text_input("Password", d["password"], type="password", key=f"{k}_pw"),
        }
    if kind in ("duckdb", "sqlite"):
        return {"path": st.text_input("Database file", d["path"], key=f"{k}_path",
                                      help="Created automatically if it does not exist.")}
    if kind == "mongodb":
        return {"uri": st.text_input("Connection URI", d["uri"], key=f"{k}_uri"),
                "database": st.text_input("Database", d["database"], key=f"{k}_db")}
    return {}


def _defect_table(source):
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            ds = json.load(f)["datasets"].get(source)
    except (OSError, ValueError):
        return None
    if not ds:
        return None
    rows = [{"defect": k.replace("_", " "), "rows affected": v["count"],
             "example": "; ".join(str(e["detail"]) for e in v["examples"][:2])}
            for k, v in ds["defects"].items()]
    return ds["rows"], pd.DataFrame(rows).sort_values("rows affected", ascending=False)


def _er_diagram(res):
    nodes = []
    for t, meta in res["target_info"].items():
        label_rows = "".join(
            f'<tr><td align="left">{"🔑 " if r.key == "PK" else ("🔗 " if r.key == "FK" else "")}{r.column_name}</td>'
            f'<td align="left"><font color="#666666">{str(r.column_type).replace("<", "&lt;").replace(">", "&gt;")}</font></td></tr>'
            for r in meta["columns"].itertuples())
        nodes.append(f'"{t}" [shape=plaintext label=<<table border="1" cellborder="0" cellspacing="0" cellpadding="3">'
                     f'<tr><td colspan="2" bgcolor="#dbeafe"><b>{t}</b></td></tr>{label_rows}</table>>];')
    edges = []
    if res.get("lookup_table"):
        edges.append(f'"{res["target_table"]}" -> "{res["lookup_table"]}" [label="  {res["normalize_column"]}_id → id  (N:1)"];')
    return "digraph { rankdir=LR; node [fontname=Helvetica fontsize=10]; edge [fontsize=9];\n" + "\n".join(nodes + edges) + "\n}"


def _endpoint_panel(role, kinds, preset):
    st.markdown(f"#### {'📥 Source' if role == 'source' else '📤 Target'}")
    kind = st.selectbox("System", kinds, format_func=lambda k: f"{ICONS[k]} {LABELS[k]}", key=f"{role}_kind",
                        index=kinds.index("postgresql" if role == "source" else "mysql"))
    table = None
    if kind == "csv":
        up = st.file_uploader("CSV file (or leave empty to use the preset's demo CSV)", type=["csv"], key="src_csv")
        if up:
            path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{os.path.basename(up.name)}")
            with open(path, "wb") as f:
                f.write(up.getbuffer())
        else:
            path = os.path.join(ROOT, "data", preset["csv"])
        cfg = {"path": path}
        st.caption(f"Reading `{os.path.basename(path)}`")
    else:
        with st.expander("Connection settings", expanded=False):
            cfg = _config_inputs(kind, role)
        default_table = preset["source"] if role == "source" else preset["target"]
        table = st.text_input("Collection" if kind == "mongodb" else "Table", default_table,
                              key=f"{role}_{kind}_tbl_{preset['source']}")
    return Endpoint(kind, cfg), table


def render_demo_tab():
    st.markdown('<div class="section-header">Migrate between any two databases, with verifiable results</div>',
                unsafe_allow_html=True)
    st.markdown(
        "Pick a dirty legacy source and a target among **PostgreSQL, MySQL, DuckDB, SQLite and MongoDB**. "
        "The pipeline cleans and validates the data, designs a typed schema with constraints for the target, "
        "loads it **atomically**, and then **proves** the result by querying both systems."
    )

    preset_label = st.radio("**1. Choose a dirty dataset**", list(PRESETS), horizontal=True, key="demo_preset")
    preset = PRESETS[preset_label]
    defects = _defect_table(preset["source"])
    if defects:
        n_rows, ddf = defects
        with st.expander(f"🧪 What's wrong with `{preset['source']}`: {int(ddf['rows affected'].sum())} injected defects across {n_rows} rows"):
            st.caption("Generated by `data/generate_dirty_data.py` (seeded, reproducible). Each defect is recorded in `data/dirty_data_manifest.json`.")
            st.dataframe(ddf, hide_index=True, use_container_width=True)

    st.markdown("**2. Source and target**")
    c_src, c_tgt = st.columns(2)
    with c_src:
        source, source_table = _endpoint_panel("source", list(SOURCE_KINDS), preset)
        b1, b2 = st.columns(2)
        if source.kind != "csv" and b1.button(f"🌱 Seed dirty `{preset['source']}` into {source.label}",
                                              use_container_width=True, key="seed_btn"):
            try:
                from data.seed_postgres import seed_endpoint
                seeded = seed_endpoint(source, [preset["source"]])
                st.success("Seeded: " + ", ".join(f"`{t}` ({n} rows, all columns as text)" for t, n in seeded.items()))
            except Exception as e:
                st.error(f"Could not seed {source.label}: {getattr(e, 'orig', e)}")
        if b2.button("🔌 Test source", use_container_width=True, key="ping_src"):
            try:
                st.success(source.ping())
            except Exception as e:
                st.error(f"{source.label} unreachable: {getattr(e, 'orig', e)}")
    with c_tgt:
        target, target_table = _endpoint_panel("target", list(TARGET_KINDS), preset)
        mode = st.radio("Schema mode", ["Flat table", "Normalized (3NF)"], horizontal=True, key=f"mode_{preset['source']}",
                        help="3NF moves a repeating column (and the columns that depend on it) into a lookup table referenced by a foreign key.")
        normalize_column = lookup_table = None
        if mode.startswith("Normalized"):
            n1, n2 = st.columns(2)
            normalize_column = n1.text_input("Column to extract", preset["normalize_column"], key=f"ncol_{preset['source']}")
            lookup_table = n2.text_input("Lookup table name", preset["lookup_table"], key=f"lk_{preset['source']}")
        if st.button("🔌 Test target", use_container_width=True, key="ping_tgt"):
            try:
                st.success(target.ping())
            except Exception as e:
                st.error(f"{target.label} unreachable: {getattr(e, 'orig', e)}")

    if st.button(f"🚀 Migrate {source.label} → {target.label}", type="primary", use_container_width=True):
        with st.spinner("Extracting → cleaning → designing schema → loading atomically → verifying..."):
            st.session_state.demo_migration_result = run_migration(
                source_table=source_table, target_table=(target_table or "").strip(),
                normalize_column=normalize_column, lookup_table=lookup_table,
                source=source, target=target,
            )
            st.session_state.demo_target = target

    res = st.session_state.get("demo_migration_result")
    if not res:
        return
    if res.get("status") == "error":
        st.error(f"❌ **Migration failed:** {res.get('message')}")
        if "rolled back" in res.get("message", "") or "untouched" in res.get("message", ""):
            st.info("The load is atomic, so the existing target tables were not modified.")
        return
    _render_result(res, st.session_state.get("demo_target", target))


def _render_result(res, target):
    loader = mongo_loader if target.kind == "mongodb" else sql_loader
    checks = res["checks"]
    passed = sum(c["passed"] for c in checks)
    stats = res["stats"]
    if res["status"] == "success":
        st.success(f"✅ **Migration verified:** {res['message']} All **{passed}/{len(checks)}** verification checks "
                   f"passed (run #{res['run_id']}).")
    else:
        st.error(f"⚠️ Data was loaded, but only {passed}/{len(checks)} verification checks passed. See the Proof tab.")

    m = st.columns(5)
    m[0].metric(f"Source rows ({res['source_system']})", stats["source_rows"])
    m[1].metric(f"Loaded rows ({res['target_system']})", stats["loaded_rows"])
    m[2].metric("Exact duplicates removed", stats["exact_duplicates_removed"])
    m[3].metric("Quarantined rows", stats["quarantined_rows"])
    m[4].metric("Verification checks", f"{passed}/{len(checks)}")
    st.caption(
        f"Row accounting: **{stats['source_rows']}** source = **{stats['loaded_rows']}** loaded + "
        f"**{stats['exact_duplicates_removed']}** duplicates + **{stats['quarantined_rows']}** quarantined. "
        f"`{res['source_location']}` → `{res['target_location']}`. "
        f"Timings: {', '.join(f'{k} {v}s' for k, v in res['timings'].items())}")
    st.info(f"**Load protocol.** {res['protocol']}")

    t_proof, t_schema, t_clean, t_data, t_hist = st.tabs(
        ["✅ Proof (live queries)", "🏗️ Schema design", "🧹 Cleaning & quarantine", "🔍 Before / after", "📜 Run history"])

    with t_proof:
        st.markdown(f"Each check below ran **just now against {res['source_system']} and {res['target_system']}**. "
                    "The query used is shown for every row.")
        cdf = pd.DataFrame([{"": "✅" if c["passed"] else "❌", "check": c["check"],
                             "expected": str(c["expected"]), "actual (from the database)": str(c["actual"])} for c in checks])
        st.dataframe(cdf, hide_index=True, use_container_width=True)
        with st.expander("Show the query behind each check"):
            for c in checks:
                st.markdown(f"**{c['check']}**")
                st.code(c["sql"], language="sql")

        st.markdown(f"##### Query {res['target_system']} live")
        queries = loader.live_queries(target, res)
        choice = st.selectbox("Pick a query", list(queries), key="live_q")
        st.code(queries[choice] if isinstance(queries[choice], str) else json.dumps(queries[choice], default=str),
                language="sql" if isinstance(queries[choice], str) else "json")
        if st.button(f"▶ Run against {res['target_system']}", key="run_live_q"):
            try:
                out = loader.run_query(target, queries[choice])
                st.caption(f"{len(out)} rows returned")
                st.dataframe(out, hide_index=True, use_container_width=True)
            except Exception as e:
                st.error(f"Query failed: {getattr(e, 'orig', e)}")
        try:
            spec = queries[list(queries)[0]]
            full = loader.run_query(target, spec.replace(" LIMIT 50", "") if isinstance(spec, str) else spec)
            st.download_button(f"📥 Download `{res['target_table']}` as CSV (read back from {res['target_system']})",
                               full.to_csv(index=False), file_name=f"{res['target_table']}.csv", mime="text/csv")
        except Exception:
            pass

    with t_schema:
        if res.get("lookup_table"):
            col, lk, deps = res["normalize_column"], res["lookup_table"], res.get("dependents") or []
            if deps:
                fd = ", ".join(f"`{col} → {d}`" for d in deps)
                st.markdown(
                    f"**3NF decomposition.** Functional dependencies detected in the data: {fd}. With "
                    f"primary key of `{res['target_table']}` → `{col}` → {', '.join(f'`{d}`' for d in deps)}, the flat table had a "
                    f"*transitive dependency*: the same {', '.join(deps)} was repeated for every row with that {col}, so it could "
                    f"be updated inconsistently. `{col}` and its dependents moved to `{lk}`; `{res['target_table']}` keeps only "
                    f"the foreign key `{col}_id`.")
            else:
                st.markdown(
                    f"**Reference table.** No other column depends on `{col}` in this data, so the flat table was already in 3NF. "
                    f"Moving `{col}` into `{lk}` (UNIQUE) with a FOREIGN KEY stores each value once and makes the database reject "
                    f"misspellings such as a new 'Markting' row. If {col}-level attributes are added later, they belong in `{lk}`.")
            if res["target_kind"] == "mongodb":
                st.caption("MongoDB has no foreign keys: the reference is by id, and orphans are checked with `$lookup`.")
        st.graphviz_chart(_er_diagram(res))
        st.markdown(f"##### Source ({res['source_system']}) → target ({res['target_system']}) type mapping")
        st.dataframe(res["type_mapping"], hide_index=True, use_container_width=True)
        for t, meta in res["target_info"].items():
            st.markdown(f"##### `{t}`: definition {meta['ddl_source']}")
            st.code(meta["ddl"], language="json" if res["target_kind"] == "mongodb" else "sql")
            st.dataframe(meta["constraints"], hide_index=True, use_container_width=True)
        exp = res.get("explain") or {}
        if exp.get("before") and exp.get("after"):
            st.markdown("##### Index effect (query plan before vs after creating the index)")
            st.code(exp["query"], language="sql")
            e1, e2 = st.columns(2)
            e1.markdown("**Before index**")
            e1.dataframe(pd.DataFrame(exp["before"]), hide_index=True)
            e2.markdown("**After index**")
            e2.dataframe(pd.DataFrame(exp["after"]), hide_index=True)
            if exp.get("note"):
                st.caption(exp["note"])

    with t_clean:
        log = pd.DataFrame(res["transformation_log"])
        log = log[log["action"] != "standardize_column_name"]
        st.dataframe(log, hide_index=True, use_container_width=True)
        q = res["quarantine"]
        st.markdown(f"##### Quarantined rows ({len(q)})")
        st.caption("These rows break key integrity, so they aren't loaded. They're stored in the target's migration "
                   "metadata with their raw source values for a data steward to review.")
        if len(q):
            st.dataframe(q, hide_index=True, use_container_width=True)

    with t_data:
        p1, p2 = st.columns(2)
        p1.markdown(f"**Raw source: {res['source_system']} `{res['source_table'] or 'upload'}`**")
        p1.dataframe(res["source_preview"].astype(str), use_container_width=True, hide_index=True)
        p2.markdown(f"**Cleaned: {res['target_system']} `{res['target_table']}`**")
        p2.dataframe(res["target_preview"], use_container_width=True, hide_index=True)

    with t_hist:
        st.dataframe(res["history"], hide_index=True, use_container_width=True)
