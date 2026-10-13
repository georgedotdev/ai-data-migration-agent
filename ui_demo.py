"""
Streamlit UI for the deterministic PostgreSQL -> MySQL migration demo.

Everything shown under "Proof" is queried live from the databases, not taken
from the pipeline's own bookkeeping.
"""

import json
import os

import pandas as pd
import streamlit as st
from sqlalchemy import text

from migration_service import run_migration

MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dirty_data_manifest.json")

PRESETS = {
    "👥 HR employees (dirty_employees)": {
        "source": "dirty_employees", "target": "employees",
        "normalize_column": "department", "lookup_table": "departments",
    },
    "🛒 Retail orders (dirty_orders)": {
        "source": "dirty_orders", "target": "orders",
        "normalize_column": "product", "lookup_table": "products",
    },
}


def _pg_config_inputs():
    st.markdown("##### PostgreSQL (source)")
    return {
        "host": st.text_input("Host", os.environ.get("PG_HOST", "127.0.0.1"), key="demo_pg_h"),
        "port": int(st.number_input("Port", value=int(os.environ.get("PG_PORT", 5432)), key="demo_pg_p")),
        "database": st.text_input("Database", os.environ.get("PG_DATABASE", "migration_db"), key="demo_pg_d"),
        "username": st.text_input("User", os.environ.get("PG_USER", "postgres"), key="demo_pg_u"),
        "password": st.text_input("Password", os.environ.get("PG_PASSWORD", ""), type="password", key="demo_pg_pw"),
    }


def _mysql_config_inputs():
    st.markdown("##### MySQL (target)")
    return {
        "host": st.text_input("Host", os.environ.get("MYSQL_HOST", "127.0.0.1"), key="demo_my_h"),
        "port": int(st.number_input("Port", value=int(os.environ.get("MYSQL_PORT", 3306)), key="demo_my_p")),
        "database": st.text_input("Database", os.environ.get("MYSQL_DATABASE", "migration_db"), key="demo_my_d"),
        "username": st.text_input("User", os.environ.get("MYSQL_USER", "root"), key="demo_my_u"),
        "password": st.text_input("Password", os.environ.get("MYSQL_PASSWORD", ""), type="password", key="demo_my_pw"),
    }


def _check_connections(pg_config, mysql_config):
    from connectors.mysql_connector import MySQLConnector
    from connectors.postgres_connector import PostgreSQLConnector
    c1, c2 = st.columns(2)
    try:
        with PostgreSQLConnector(**pg_config).engine.connect() as c:
            c1.success(f"PostgreSQL OK: {c.execute(text('SELECT version()')).scalar().split(',')[0]}")
    except Exception as e:
        c1.error(f"PostgreSQL unreachable: {getattr(e, 'orig', e)}")
    try:
        with MySQLConnector(**mysql_config).engine.connect() as c:
            c2.success(f"MySQL OK: version {c.execute(text('SELECT VERSION()')).scalar()}")
    except Exception as e:
        c2.error(f"MySQL unreachable: {getattr(e, 'orig', e)}")


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
    """Graphviz DOT for the tables that were created."""
    info = res["target_info"]
    nodes = []
    for t, meta in info.items():
        cols = meta["columns"]
        label_rows = "".join(
            f'<tr><td align="left">{"🔑 " if r.key == "PRI" else ("🔗 " if r.key == "MUL" and r.column_name.endswith("_id") else "")}'
            f'{r.column_name}</td><td align="left"><font color="#666666">{r.column_type}</font></td></tr>'
            for r in cols.itertuples()
        )
        nodes.append(f'"{t}" [shape=plaintext label=<<table border="1" cellborder="0" cellspacing="0" cellpadding="3">'
                     f'<tr><td colspan="2" bgcolor="#dbeafe"><b>{t}</b></td></tr>{label_rows}</table>>];')
    edges = []
    if res.get("lookup_table"):
        edges.append(f'"{res["target_table"]}" -> "{res["lookup_table"]}" [label="  {res["normalize_column"]}_id → id  (N:1)"];')
    return "digraph { rankdir=LR; node [fontname=Helvetica fontsize=10]; edge [fontsize=9];\n" + "\n".join(nodes + edges) + "\n}"


def _live_queries(res):
    t = res["target_table"]
    queries = {
        f"First 50 rows of `{t}`": f"SELECT * FROM `{t}` LIMIT 50",
        "Migration run history (metadata table)": "SELECT * FROM migration_runs ORDER BY run_id DESC LIMIT 20",
        "Transformation steps of this run": f"SELECT step_no, column_name, action, rows_affected, detail FROM migration_steps WHERE run_id = {int(res['run_id'])} ORDER BY step_no",
        "Quarantined rows of this run": f"SELECT source_row, reason, raw_row FROM migration_quarantine WHERE run_id = {int(res['run_id'])}",
    }
    if res.get("lookup_table"):
        lk, col = res["lookup_table"], res["normalize_column"]
        money = next((r.mysql_column for r in res["type_mapping"].itertuples()
                      if r.detected_as == "money" and r.target_table == t), None)
        agg = f", ROUND(AVG(m.`{money}`), 2) AS avg_{money}" if money else ""
        queries[f"JOIN `{t}` with `{lk}` (aggregate per {col})"] = (
            f"SELECT l.`{col}`, COUNT(*) AS n{agg} FROM `{t}` m JOIN `{lk}` l ON m.`{col}_id` = l.id "
            f"GROUP BY l.`{col}` ORDER BY n DESC")
    return queries


def render_demo_tab():
    st.markdown('<div class="section-header">PostgreSQL → MySQL migration with verifiable results</div>', unsafe_allow_html=True)
    st.markdown(
        "Extract a dirty legacy table from **PostgreSQL**, clean and validate it, design a typed MySQL schema "
        "with constraints, load it **transactionally**, then **prove** the result with SQL run against both databases."
    )

    with st.expander("⚙️ Database connections & source seeding", expanded=False):
        c_pg, c_my = st.columns(2)
        with c_pg:
            pg_config = _pg_config_inputs()
        with c_my:
            mysql_config = _mysql_config_inputs()
        b1, b2 = st.columns(2)
        if b1.button("🔌 Test connections", use_container_width=True):
            _check_connections(pg_config, mysql_config)
        if b2.button("🌱 (Re)seed dirty source tables in PostgreSQL", use_container_width=True):
            try:
                from data.seed_postgres import seed_postgres
                seeded = seed_postgres(pg_config)
                st.success("Seeded: " + ", ".join(f"`{t}` ({n} rows)" for t, n in seeded.items()))
            except Exception as e:
                st.error(f"Could not seed PostgreSQL: {getattr(e, 'orig', e)}")

    preset_label = st.radio("**1. Choose a dirty source dataset**", list(PRESETS), horizontal=True, key="demo_preset")
    preset = PRESETS[preset_label]

    defects = _defect_table(preset["source"])
    if defects:
        n_rows, ddf = defects
        with st.expander(f"🧪 What's wrong with `{preset['source']}`: {int(ddf['rows affected'].sum())} injected defects across {n_rows} rows", expanded=False):
            st.caption("Generated by `data/generate_dirty_data.py` (seeded, reproducible). Each defect is recorded in `data/dirty_data_manifest.json`.")
            st.dataframe(ddf, hide_index=True, use_container_width=True)

    st.markdown("**2. Target design**")
    o1, o2, o3 = st.columns([2, 2, 3])
    target_table = o1.text_input("Target table in MySQL", preset["target"], key=f"tgt_{preset['source']}")
    mode = o2.radio("Schema mode", ["Flat table", "Normalized (3NF)"], key=f"mode_{preset['source']}",
                    help="3NF extracts a repeating category into its own lookup table, linked with a FOREIGN KEY.")
    normalize_column = lookup_table = None
    if mode.startswith("Normalized"):
        n1, n2 = o3.columns(2)
        normalize_column = n1.text_input("Column to extract", preset["normalize_column"], key=f"ncol_{preset['source']}")
        lookup_table = n2.text_input("Lookup table name", preset["lookup_table"], key=f"lk_{preset['source']}")

    if st.button("🚀 Run migration", type="primary", use_container_width=True):
        with st.spinner("Extracting → cleaning → designing schema → loading transactionally → verifying..."):
            st.session_state.demo_migration_result = run_migration(
                source_table=preset["source"], target_table=target_table.strip(),
                pg_config=pg_config, mysql_config=mysql_config,
                normalize_column=normalize_column, lookup_table=lookup_table,
            )
            st.session_state.demo_mysql_config = mysql_config

    res = st.session_state.get("demo_migration_result")
    if not res:
        return
    if res.get("status") == "error":
        st.error(f"❌ **Migration failed:** {res.get('message')}")
        if "rolled back" in res.get("message", ""):
            st.info("The load runs in a transaction on staging tables, so the live MySQL tables were not modified.")
        return
    _render_result(res, st.session_state.get("demo_mysql_config", mysql_config))


def _render_result(res, mysql_config):
    from connectors.mysql_connector import MySQLConnector

    checks = res["checks"]
    passed = sum(c["passed"] for c in checks)
    stats = res["stats"]
    if res["status"] == "success":
        st.success(f"✅ **Migration verified:** {res['message']} All **{passed}/{len(checks)}** SQL verification checks passed (run #{res['run_id']}).")
    else:
        st.error(f"⚠️ Data was loaded, but only {passed}/{len(checks)} verification checks passed. See the Proof tab.")

    m = st.columns(5)
    m[0].metric("Source rows (PostgreSQL)", stats["source_rows"])
    m[1].metric("Loaded rows (MySQL)", stats["loaded_rows"])
    m[2].metric("Exact duplicates removed", stats["exact_duplicates_removed"])
    m[3].metric("Quarantined rows", stats["quarantined_rows"])
    m[4].metric("Verification checks", f"{passed}/{len(checks)}")
    st.caption(
        f"Row accounting: **{stats['source_rows']}** source = **{stats['loaded_rows']}** loaded + "
        f"**{stats['exact_duplicates_removed']}** duplicates + **{stats['quarantined_rows']}** quarantined. "
        "This is also enforced by a CHECK constraint on `migration_runs`. "
        f"Timings: {', '.join(f'{k} {v}s' for k, v in res['timings'].items())}"
    )

    t_proof, t_schema, t_clean, t_data, t_hist = st.tabs(
        ["✅ Proof (live SQL)", "🏗️ Schema design", "🧹 Cleaning & quarantine", "🔍 Before / after", "📜 Run history"])

    with t_proof:
        st.markdown("Each check below ran **just now against the real databases**. The SQL used is shown for every row.")
        cdf = pd.DataFrame([{"": "✅" if c["passed"] else "❌", "check": c["check"],
                             "expected": str(c["expected"]), "actual (from DB)": str(c["actual"])} for c in checks])
        st.dataframe(cdf, hide_index=True, use_container_width=True)
        with st.expander("Show the SQL behind each check"):
            for c in checks:
                st.markdown(f"**{c['check']}**")
                st.code(c["sql"], language="sql")

        st.markdown("##### Query MySQL live")
        queries = _live_queries(res)
        choice = st.selectbox("Pick a query", list(queries), key="live_q")
        st.code(queries[choice], language="sql")
        if st.button("▶ Run against MySQL", key="run_live_q"):
            try:
                eng = MySQLConnector(**mysql_config).engine
                with eng.connect() as c:
                    out = pd.read_sql(text(queries[choice]), c)
                st.caption(f"{len(out)} rows returned by MySQL")
                st.dataframe(out, hide_index=True, use_container_width=True)
            except Exception as e:
                st.error(f"Query failed: {getattr(e, 'orig', e)}")

        try:
            eng = MySQLConnector(**mysql_config).engine
            with eng.connect() as c:
                full = pd.read_sql(text(f"SELECT * FROM `{res['target_table']}`"), c)
            st.download_button(f"📥 Download `{res['target_table']}` as CSV (read from MySQL, {len(full)} rows)",
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
                    f"Moving `{col}` into `{lk}` (UNIQUE) with a FOREIGN KEY stores each value once and makes MySQL reject "
                    f"misspellings such as a new 'Markting' row. If {col}-level attributes are added later, they belong in `{lk}`.")
        st.graphviz_chart(_er_diagram(res))
        st.markdown("##### Source → target type mapping")
        st.dataframe(res["type_mapping"], hide_index=True, use_container_width=True)
        for t, meta in res["target_info"].items():
            st.markdown(f"##### `SHOW CREATE TABLE {t}` (from MySQL)")
            st.code(meta["ddl"], language="sql")
            st.dataframe(meta["constraints"], hide_index=True, use_container_width=True)
        exp = res.get("explain") or {}
        if exp.get("before") and exp.get("after"):
            st.markdown("##### Index effect (EXPLAIN before vs after `CREATE INDEX`)")
            st.code(exp["query"], language="sql")
            e1, e2 = st.columns(2)
            keep = ["type", "possible_keys", "key", "rows", "Extra"]
            e1.markdown("**Before index**")
            e1.dataframe(pd.DataFrame(exp["before"])[keep], hide_index=True)
            e2.markdown("**After index**")
            e2.dataframe(pd.DataFrame(exp["after"])[keep], hide_index=True)
            st.caption("`type=ALL` is a full table scan; `type=ref` uses the index to read only matching rows.")

    with t_clean:
        log = pd.DataFrame(res["transformation_log"])
        log = log[log["action"] != "standardize_column_name"]
        st.dataframe(log, hide_index=True, use_container_width=True)
        q = res["quarantine"]
        st.markdown(f"##### Quarantined rows ({len(q)})")
        st.caption("These rows break key integrity, so they aren't loaded. They're stored in `migration_quarantine` "
                   "with the raw source values for a data steward to review.")
        if len(q):
            st.dataframe(q, hide_index=True, use_container_width=True)

    with t_data:
        p1, p2 = st.columns(2)
        p1.markdown(f"**Raw source: PostgreSQL `{res['source_table']}`**")
        p1.dataframe(res["source_preview"], use_container_width=True, hide_index=True)
        p2.markdown(f"**Cleaned: MySQL `{res['target_table']}`**")
        p2.dataframe(res["target_preview"], use_container_width=True, hide_index=True)

    with t_hist:
        st.dataframe(res["history"], hide_index=True, use_container_width=True)
