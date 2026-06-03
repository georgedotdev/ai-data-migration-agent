"""
AI Data Migration Agent — Dashboard

Multi-connector operational console with AI-powered planning.

Supports:
    CSV / PostgreSQL / MongoDB → DuckDB / PostgreSQL / MongoDB

Workflow:
    Prompt → AI Planner → Plan Review → Execute → Validate → Report → Download
"""

import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime

from migration_service import (
    generate_ai_plan,
    run_full_migration,
    load_reports
)
from connectors.connector_factory import get_connector


# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="AI Data Migration Agent",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ─────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    .dashboard-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.8rem 2rem; border-radius: 12px;
        margin-bottom: 1.5rem; color: white;
    }
    .dashboard-header h1 { margin: 0; font-size: 1.8rem; font-weight: 700; }
    .dashboard-header p { margin: 0.3rem 0 0 0; opacity: 0.85; font-size: 0.95rem; }
    .step-card {
        padding: 0.7rem 1rem; margin: 0.35rem 0; border-radius: 8px;
        display: flex; align-items: center; gap: 0.6rem;
        font-size: 0.95rem; font-weight: 500;
    }
    .step-pass { background: rgba(0,217,126,0.10); border-left: 4px solid #00D97E; color: #00D97E; }
    .step-fail { background: rgba(230,55,87,0.10); border-left: 4px solid #E63757; color: #E63757; }
    .step-pending { background: rgba(149,170,201,0.08); border-left: 4px solid #95AAC9; color: #95AAC9; }
    .validation-pass { color: #00D97E; font-weight: 600; font-size: 1.05rem; }
    .validation-fail { color: #E63757; font-weight: 600; font-size: 1.05rem; }
    .section-header {
        font-size: 1.15rem; font-weight: 600; margin-bottom: 0.8rem;
        padding-bottom: 0.4rem; border-bottom: 2px solid rgba(108,99,255,0.3);
    }
    section[data-testid="stSidebar"] > div { padding-top: 1.5rem; }
    [data-testid="stMetricValue"] { font-size: 1.3rem; }
    .plan-card {
        background: rgba(102,126,234,0.08); border: 1px solid rgba(102,126,234,0.25);
        border-radius: 10px; padding: 1.2rem 1.5rem; margin: 0.5rem 0;
    }
    .plan-card h4 { margin: 0 0 0.3rem 0; color: #667eea; font-size: 0.95rem; }
    .plan-card p { margin: 0; font-size: 0.92rem; }
    .method-badge-ai {
        display: inline-block; background: linear-gradient(135deg, #667eea, #764ba2);
        color: white; padding: 0.2rem 0.7rem; border-radius: 12px;
        font-size: 0.78rem; font-weight: 600;
    }
    .method-badge-deterministic {
        display: inline-block; background: rgba(149,170,201,0.2);
        color: #95AAC9; padding: 0.2rem 0.7rem; border-radius: 12px;
        font-size: 0.78rem; font-weight: 600;
    }
    .reasoning-item {
        padding: 0.6rem 0.9rem; margin: 0.3rem 0; border-radius: 6px;
        background: rgba(108,99,255,0.04); border-left: 3px solid #667eea;
        font-size: 0.88rem;
    }
    .reasoning-label {
        font-weight: 600; color: #667eea; font-size: 0.82rem;
        text-transform: uppercase; letter-spacing: 0.5px;
    }
    .diag-header {
        color: #E63757; font-size: 1.15rem; font-weight: 600;
        margin-bottom: 0.8rem; padding-bottom: 0.4rem;
        border-bottom: 2px solid rgba(230,55,87,0.3);
    }
    .download-section {
        background: rgba(0,217,126,0.08); border: 2px solid rgba(0,217,126,0.3);
        border-radius: 12px; padding: 1.5rem; text-align: center; margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────

for key in [
    "ai_plan", "ai_schema", "migration_result",
    "migration_ran", "source_config", "target_config"
]:
    if key not in st.session_state:
        st.session_state[key] = (
            False if key == "migration_ran"
            else ({} if key.endswith("_config") else None)
        )


# ─────────────────────────────────────────────
# Sidebar — Configuration
# ─────────────────────────────────────────────

with st.sidebar:

    # ─── Source Configuration ───
    st.markdown("### 📥 Source Configuration")

    source_type = st.selectbox(
        "Source Connector",
        ["CSV", "PostgreSQL", "MongoDB"],
        format_func=lambda x: f"✅ {x}"
    )

    source_config = {}

    if source_type == "CSV":
        uploaded_file = st.file_uploader(
            "📁 Upload CSV File", type=["csv"]
        )
    elif source_type == "PostgreSQL":
        uploaded_file = None
        st.caption("🔌 PostgreSQL Source Connection")
        src_pg_host = st.text_input("Host", "localhost", key="src_pg_host")
        src_pg_port = st.number_input("Port", value=5432, key="src_pg_port")
        src_pg_db = st.text_input("Database", "migration_db", key="src_pg_db")
        src_pg_user = st.text_input("Username", "migration", key="src_pg_user")
        src_pg_pass = st.text_input("Password", "migration123", type="password", key="src_pg_pass")
        src_pg_table = st.text_input("Table", "enterprise", key="src_pg_table")
        source_config = {
            "host": src_pg_host, "port": int(src_pg_port),
            "database": src_pg_db, "username": src_pg_user,
            "password": src_pg_pass, "table_name": src_pg_table
        }
    elif source_type == "MongoDB":
        uploaded_file = None
        st.caption("🔌 MongoDB Source Connection")
        src_mongo_conn = st.text_input("Connection String", "mongodb://localhost:27017", key="src_mongo_conn")
        src_mongo_db = st.text_input("Database", "migration_db", key="src_mongo_db")
        src_mongo_coll = st.text_input("Collection", "enterprise", key="src_mongo_coll")
        source_config = {
            "connection_string": src_mongo_conn,
            "database": src_mongo_db,
            "collection": src_mongo_coll
        }
    else:
        uploaded_file = None

    st.markdown("---")

    # ─── Target Configuration ───
    st.markdown("### 📤 Target Configuration")

    target_type = st.selectbox(
        "Target Connector",
        ["DuckDB", "PostgreSQL", "MongoDB"],
        format_func=lambda x: f"✅ {x}"
    )

    target_config = {}
    has_target_config = False
    target_mode = "generate"

    if target_type == "DuckDB":
        target_mode = st.radio(
            "Target Mode",
            ["Generate Target (Download)", "Existing Target"],
            key="duckdb_mode"
        )
        if target_mode == "Existing Target":
            uploaded_duckdb = st.file_uploader(
                "📁 Upload .duckdb file",
                type=["duckdb"],
                key="duckdb_upload"
            )
            if uploaded_duckdb:
                os.makedirs("data", exist_ok=True)
                duckdb_path = os.path.join("data", uploaded_duckdb.name)
                with open(duckdb_path, "wb") as f:
                    f.write(uploaded_duckdb.getbuffer())
                target_config = {
                    "db_path": duckdb_path,
                    "table_name": "enterprise"
                }
                has_target_config = True
        else:
            st.caption("🟢 DuckDB file will be auto-generated for download")

    elif target_type == "PostgreSQL":
        target_mode = "existing"
        st.caption("🔌 PostgreSQL Target Connection")
        tgt_pg_host = st.text_input("Host", "localhost", key="tgt_pg_host")
        tgt_pg_port = st.number_input("Port", value=5432, key="tgt_pg_port")
        tgt_pg_db = st.text_input("Database", "migration_db", key="tgt_pg_db")
        tgt_pg_user = st.text_input("Username", "migration", key="tgt_pg_user")
        tgt_pg_pass = st.text_input("Password", "migration123", type="password", key="tgt_pg_pass")
        tgt_pg_table = st.text_input("Target Table", "enterprise_migrated", key="tgt_pg_table")
        target_config = {
            "host": tgt_pg_host, "port": int(tgt_pg_port),
            "database": tgt_pg_db, "username": tgt_pg_user,
            "password": tgt_pg_pass, "table_name": tgt_pg_table
        }
        has_target_config = bool(
            tgt_pg_host and tgt_pg_db and tgt_pg_user
        )

    elif target_type == "MongoDB":
        target_mode = "existing"
        st.caption("🔌 MongoDB Target Connection")
        tgt_mongo_conn = st.text_input("Connection String", "mongodb://localhost:27017", key="tgt_mongo_conn")
        tgt_mongo_db = st.text_input("Database", "migration_db", key="tgt_mongo_db")
        tgt_mongo_coll = st.text_input("Collection", "enterprise_migrated", key="tgt_mongo_coll")
        target_config = {
            "connection_string": tgt_mongo_conn,
            "database": tgt_mongo_db,
            "collection": tgt_mongo_coll
        }
        has_target_config = bool(
            tgt_mongo_conn and tgt_mongo_db and tgt_mongo_coll
        )

    st.markdown("---")

    # ─── AI Configuration ───
    st.markdown("### 🔑 AI Configuration")
    ai_provider = st.selectbox(
        "Planning Provider",
        ["Deterministic", "Gemini", "OpenAI"],
        help="Choose AI provider for migration planning"
    )

    api_key = None
    if ai_provider == "Gemini":
        api_key = st.text_input(
            "Gemini API Key", type="password",
            help="Google AI API key for Gemini planning"
        )
        if api_key:
            st.caption("🟢 Gemini AI planning enabled")
        else:
            st.caption("⚠️ Enter API key to enable Gemini")
    elif ai_provider == "OpenAI":
        api_key = st.text_input(
            "OpenAI API Key", type="password",
            help="OpenAI API key for GPT planning"
        )
        if api_key:
            st.caption("🟢 OpenAI planning enabled")
        else:
            st.caption("⚠️ Enter API key to enable OpenAI")
    else:
        st.caption("⚙️ Deterministic planning (no AI)")

    st.markdown("---")
    st.markdown("### 📜 Quick Info")
    st.caption("**Workflow:** AI Planner → Retriever → Executor → Tester → Supervisor")
    st.caption("**Engine:** LangGraph StateGraph")
    st.caption("**Connectors:** CSV · DuckDB · PostgreSQL · MongoDB")


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────

st.markdown("""
<div class="dashboard-header">
    <h1>🔄 AI Data Migration Console</h1>
    <p>Multi-connector migration platform with AI-powered planning</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Migration Request
# ─────────────────────────────────────────────

st.markdown(
    '<div class="section-header">📝 Migration Request</div>',
    unsafe_allow_html=True
)

user_request = st.text_area(
    "Describe your migration in natural language",
    placeholder=(
        'Examples:\n'
        '"Migrate enterprise.csv to DuckDB"\n'
        '"Load customer data into PostgreSQL"\n'
        '"Migrate sales data from PostgreSQL to MongoDB"'
    ),
    height=80,
    label_visibility="collapsed"
)

# Determine if source is ready
if source_type == "CSV":
    source_ready = uploaded_file is not None
elif source_type in ("PostgreSQL", "MongoDB"):
    source_ready = bool(source_config)
else:
    source_ready = False

# Connection warnings
if target_type in ("PostgreSQL", "MongoDB") and not has_target_config:
    db_name = target_type
    st.warning(
        f"⚠️ {db_name} requires a running database instance. "
        f"Please provide connection details in the sidebar."
    )

# ─── Action Buttons ───
col_btn1, col_btn2, col_btn_space = st.columns([1, 1, 2])

with col_btn1:
    plan_disabled = not (source_ready and user_request)
    generate_plan_btn = st.button(
        "🧠 Generate Plan",
        type="primary",
        use_container_width=True,
        disabled=plan_disabled
    )

with col_btn2:
    can_execute = (
        st.session_state.ai_plan is not None
        and not (
            st.session_state.ai_plan.get("requires_connection")
            and not has_target_config
        )
    )
    execute_btn = st.button(
        "🚀 Execute Migration",
        type="secondary",
        use_container_width=True,
        disabled=not can_execute
    )

if plan_disabled and not source_ready:
    if source_type == "CSV":
        st.caption("Upload a CSV file and enter a request to generate a plan")
    else:
        st.caption("Configure source connection and enter a request")


# ─────────────────────────────────────────────
# Generate Plan
# ─────────────────────────────────────────────

if generate_plan_btn and source_ready and user_request:

    # Build source config
    if source_type == "CSV" and uploaded_file:
        os.makedirs("data", exist_ok=True)
        save_path = os.path.join("data", uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        source_config = {"file_path": save_path}

    with st.spinner("🧠 AI is analyzing your request..."):
        try:
            plan_result = generate_ai_plan(
                user_request=user_request,
                source_type=source_type.lower(),
                source_config=source_config,
                target_type_hint=target_type.lower(),
                has_target_config=has_target_config,
                api_key=api_key if api_key else None,
                provider=ai_provider.lower()
            )
            st.session_state.ai_plan = plan_result["plan"]
            st.session_state.ai_schema = plan_result["schema"]
            st.session_state.source_config = source_config
            st.session_state.target_config = target_config
            st.session_state.migration_result = None
            st.session_state.migration_ran = False
            st.rerun()
        except Exception as e:
            st.error(f"❌ Plan generation failed: {e}")


# ─────────────────────────────────────────────
# Display Generated Plan
# ─────────────────────────────────────────────

if st.session_state.ai_plan:
    plan = st.session_state.ai_plan

    st.markdown("---")
    st.markdown(
        '<div class="section-header">🧠 AI-Generated Migration Plan</div>',
        unsafe_allow_html=True
    )

    # Method badge
    method = plan.get("planning_method", "deterministic")
    if method in ("ai", "gemini"):
        badge_cls = "method-badge-ai"
        badge_icon = (
            "🤖 Gemini AI" if method == "gemini"
            else "🤖 OpenAI"
        )
    else:
        badge_cls = "method-badge-deterministic"
        badge_icon = "⚙️ Deterministic"
    st.markdown(f'<span class="{badge_cls}">{badge_icon} Plan</span>', unsafe_allow_html=True)
    st.markdown("")

    # Plan cards
    pc1, pc2, pc3 = st.columns(3)
    with pc1:
        st.markdown(
            f'<div class="plan-card"><h4>📥 Source</h4>'
            f'<p>{plan.get("source_type", "csv").upper()}</p></div>',
            unsafe_allow_html=True
        )
    with pc2:
        st.markdown(
            f'<div class="plan-card"><h4>📤 Target</h4>'
            f'<p>{plan.get("target_type", "duckdb").upper()}</p></div>',
            unsafe_allow_html=True
        )
    with pc3:
        st.markdown(
            f'<div class="plan-card"><h4>🏷️ Table Name</h4>'
            f'<p>{plan.get("table_name", "—")}</p></div>',
            unsafe_allow_html=True
        )

    # Target mode indicator
    if plan.get("generate_target"):
        st.info("📦 A DuckDB file will be generated and available for download after migration")
    elif plan.get("requires_connection") and not has_target_config:
        target_db = plan.get("target_type", "").upper()
        st.error(
            f"🔌 {target_db} requires connection details. "
            f"Please configure the target in the sidebar."
        )

    # Transformations and Validations
    tc1, tc2 = st.columns(2)
    transform_labels = {
        "normalize_columns": "📐 Normalize Columns",
        "handle_nulls": "🚫 Handle Nulls",
        "type_conversion": "🔢 Type Conversion"
    }
    validation_labels = {
        "row_count": "📊 Row Count Verification",
        "checksum": "🔐 SHA-256 Checksum"
    }

    with tc1:
        st.markdown(
            '<div class="plan-card"><h4>🔧 Transformations</h4></div>',
            unsafe_allow_html=True
        )
        for t in plan.get("transformations", []):
            st.markdown(f"  ✅ {transform_labels.get(t, t)}")
        if not plan.get("transformations"):
            st.markdown("  ⚪ No transformations selected")

    with tc2:
        st.markdown(
            '<div class="plan-card"><h4>🛡️ Validations</h4></div>',
            unsafe_allow_html=True
        )
        for v in plan.get("validations", []):
            st.markdown(f"  ✅ {validation_labels.get(v, v)}")
        if not plan.get("validations"):
            st.markdown("  ⚪ No validations selected")

    # AI Reasoning
    reasoning = plan.get("reasoning", {})
    if reasoning:
        st.markdown("")
        with st.expander("💡 AI Reasoning — Why these decisions?", expanded=True):
            items = [
                ("Source Type", reasoning.get("source_type", "")),
                ("Target Type", reasoning.get("target_type", "")),
                ("Target Mode", reasoning.get("target_mode", "")),
                ("Table Name", reasoning.get("table_name", "")),
                ("Transformations", reasoning.get("transformations", "")),
                ("Validations", reasoning.get("validations", "")),
            ]
            for label, text in items:
                if text:
                    st.markdown(
                        f'<div class="reasoning-item">'
                        f'<span class="reasoning-label">{label}</span>'
                        f'<br/>{text}</div>',
                        unsafe_allow_html=True
                    )


# ─────────────────────────────────────────────
# Execute Migration
# ─────────────────────────────────────────────

if execute_btn and st.session_state.ai_plan:
    plan = st.session_state.ai_plan
    s_config = dict(st.session_state.source_config or {})
    t_config = dict(st.session_state.target_config or {})

    # Re-save CSV if needed
    if source_type == "CSV" and uploaded_file and not s_config:
        os.makedirs("data", exist_ok=True)
        save_path = os.path.join("data", uploaded_file.name)
        if not os.path.exists(save_path):
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
        s_config = {"file_path": save_path}

    tbl_name = plan.get("table_name", "enterprise")
    gen_target = plan.get("generate_target", False)

    with st.spinner("⏳ Running migration pipeline..."):
        try:
            result = run_full_migration(
                source_type=plan.get("source_type", "csv"),
                target_type=plan.get("target_type", "duckdb"),
                source_config=s_config,
                target_config=t_config,
                table_name=tbl_name,
                transformations=plan.get("transformations"),
                validations=plan.get("validations"),
                generate_target=gen_target
            )
            st.session_state.migration_result = result
            st.session_state.migration_ran = True
        except Exception as e:
            st.error(f"❌ Migration failed: {e}")
            st.session_state.migration_result = None
            st.session_state.migration_ran = False


# ─────────────────────────────────────────────
# Display Results
# ─────────────────────────────────────────────

if st.session_state.migration_ran and st.session_state.migration_result:
    data = st.session_state.migration_result
    schema = data.get("schema", {})
    result_state = data.get("result", {})
    report = data.get("report", {})
    timings = result_state.get("timings", {})
    validation = result_state.get("validation_results", {})
    executed_steps = result_state.get("executed_steps", [])
    success = result_state.get("success", False)
    output_file = data.get("output_file_path", "")

    st.markdown("---")

    # ─── Success / Fail Banner ───
    if success:
        st.success("✅ Migration completed successfully")
    else:
        st.error("❌ Migration failed — rollback executed")

    # ─── Download Button (Generated DuckDB) ───
    if success and output_file and os.path.exists(output_file):
        st.markdown(
            '<div class="download-section">'
            '<p style="font-size:1.3rem; margin:0 0 0.5rem 0;">📦</p>'
            '<p style="font-weight:600; margin:0;">Migration artifact ready</p>'
            '</div>',
            unsafe_allow_html=True
        )
        with open(output_file, "rb") as f:
            file_bytes = f.read()
        file_size = len(file_bytes) / (1024 * 1024)
        st.download_button(
            f"📥 Download {os.path.basename(output_file)} ({file_size:.1f} MB)",
            data=file_bytes,
            file_name=os.path.basename(output_file),
            mime="application/octet-stream",
            use_container_width=True
        )

    # ─── Pipeline + Validation ───
    col_pipeline, col_spacer, col_validation = st.columns([3, 0.3, 2])

    with col_pipeline:
        st.markdown(
            '<div class="section-header">📊 Pipeline Status</div>',
            unsafe_allow_html=True
        )
        for label, key in [("Extract","extract"),("Transform","transform"),("Load","load"),("Validate","validate")]:
            is_done = key in executed_steps or key == "validate"
            step_time = timings.get(key)
            time_str = f"  —  {step_time}s" if step_time else ""
            if is_done and (key != "validate" or success):
                css, icon = "step-pass", "✅"
            elif is_done and key == "validate" and not success:
                css, icon = "step-fail", "❌"
            else:
                css, icon = "step-pending", "⏳"
            st.markdown(
                f'<div class="step-card {css}">{icon} {label}{time_str}</div>',
                unsafe_allow_html=True
            )

    with col_validation:
        st.markdown(
            '<div class="section-header">🛡️ Validation Results</div>',
            unsafe_allow_html=True
        )
        checks = []
        if "row_count" in validation:
            checks.append(("Row Count Validation", validation["row_count"]))
        if "checksum" in validation:
            checks.append(("Checksum Validation", validation["checksum"]))
        checks.append(("Overall Migration", validation.get("overall_success", False)))
        for label, passed in checks:
            css = "validation-pass" if passed else "validation-fail"
            icon = "✅" if passed else "❌"
            st.markdown(
                f'<div class="{css}">{icon}  {label}</div>',
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ─── Diagnostics on Failure ───
    diagnostics = validation.get("diagnostics")
    if diagnostics and diagnostics.get("mismatches"):
        st.markdown(
            '<div class="diag-header">🔬 Validation Diagnostics</div>',
            unsafe_allow_html=True
        )
        diag_m = diagnostics.get("mismatches", [])
        diag_c = diagnostics.get("mismatched_columns", [])
        total_f = diagnostics.get("total_mismatches_found", 0)
        total_s = diagnostics.get("total_mismatches_shown", 0)
        d1, d2, d3 = st.columns(3)
        d1.metric("Mismatches Found", f"{total_f:,}")
        d2.metric("Columns Affected", len(diag_c))
        d3.metric("Showing", f"{total_s} of {total_f}")
        if diag_c:
            st.caption(f"**Affected columns:** {', '.join(diag_c)}")
        if diag_m:
            mismatch_df = pd.DataFrame(diag_m)
            mismatch_df.columns = ["Column", "Row", "Source Value", "Target Value"]
            st.dataframe(mismatch_df, use_container_width=True, hide_index=True)
        st.markdown("---")

    # ─── Timing Metrics ───
    st.markdown('<div class="section-header">⏱️ Timing Metrics</div>', unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Extract", f"{timings.get('extract', '—')}s")
    m2.metric("Transform", f"{timings.get('transform', '—')}s")
    m3.metric("Load", f"{timings.get('load', '—')}s")
    m4.metric("Validate", f"{timings.get('validate', '—')}s")
    m5.metric("Total", f"{timings.get('total', '—')}s")
    st.markdown("---")

    # ─── Schema Discovery ───
    st.markdown('<div class="section-header">🔍 Schema Discovery</div>', unsafe_allow_html=True)
    s1, s2, s3 = st.columns(3)
    s1.metric("Row Count", f"{schema.get('row_count', 0):,}")
    s2.metric("Column Count", schema.get("column_count", 0))
    pk = schema.get("primary_key_candidates", [])
    s3.metric("PK Candidates", ", ".join(pk) if pk else "None")
    columns_data = schema.get("columns", [])
    if columns_data:
        schema_df = pd.DataFrame(columns_data)
        schema_df.columns = ["Column Name", "Data Type", "Nullable", "Unique"]
        st.dataframe(schema_df, use_container_width=True, hide_index=True)
    st.markdown("---")

    # ─── Data Preview ───
    with st.expander("📋 Data Preview", expanded=False):
        prev1, prev2 = st.columns(2)
        with prev1:
            st.markdown("**Source Data** (first 10 rows)")
            try:
                s_type = result_state.get("source_type", "csv").lower()
                s_cfg = result_state.get("source_config") or st.session_state.source_config
                src = get_connector(s_type, **s_cfg)
                src_df = src.read_data()
                st.dataframe(src_df.head(10), use_container_width=True, hide_index=True)
            except Exception:
                st.info("Source not available for preview")
        with prev2:
            st.markdown("**Target Data** (first 10 rows)")
            try:
                t_type = result_state.get("target_type", "duckdb").lower()
                t_cfg = result_state.get("target_config") or report.get("target_config", {})
                tgt = get_connector(t_type, **t_cfg)
                tgt_df = tgt.read_data()
                st.dataframe(tgt_df.head(10), use_container_width=True, hide_index=True)
            except Exception:
                st.info("Target not available for preview")

    # ─── Migration Report ───
    with st.expander("📄 Migration Report", expanded=False):
        report_display = {
            "Timestamp": report.get("timestamp", ""),
            "Source Type": report.get("source_type", ""),
            "Target Type": report.get("target_type", ""),
            "Table Name": report.get("table_name", ""),
            "Transformations": report.get("transformations", []),
            "Validations": report.get("validations", []),
            "Executed Steps": report.get("executed_steps", []),
            "Success": report.get("success", False),
            "Validation Results": report.get("validation_results", {}),
            "Timings": report.get("timings", {}),
            "Output File": report.get("output_file_path", "")
        }
        st.json(report_display)
        report_json = json.dumps(report_display, indent=2, default=str)
        st.download_button(
            "📥 Download Report JSON",
            data=report_json,
            file_name=f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

elif not st.session_state.migration_ran and not st.session_state.ai_plan:
    st.markdown("---")
    _, c, _ = st.columns([1, 2, 1])
    with c:
        st.markdown(
            '<div style="text-align:center; padding:3rem 0; opacity:0.6;">'
            '<p style="font-size:3rem; margin-bottom:0.5rem;">🧠</p>'
            '<p style="font-size:1.1rem; font-weight:500;">'
            'Describe your migration and configure connectors</p>'
            '<p style="font-size:0.9rem;">'
            'CSV · PostgreSQL · MongoDB → DuckDB · PostgreSQL · MongoDB</p>'
            '</div>',
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────
# Historical Runs
# ─────────────────────────────────────────────

st.markdown("---")
st.markdown('<div class="section-header">📜 Historical Runs</div>', unsafe_allow_html=True)

reports = load_reports()
if reports:
    history_data = []
    for r in reports:
        history_data.append({
            "Timestamp": r.get("timestamp", "")[:19],
            "Source": r.get("source_type", "").upper(),
            "Target": r.get("target_type", "").upper(),
            "Table": r.get("table_name", ""),
            "Status": "✅ Pass" if r.get("success") else "❌ Fail",
            "Total": f"{r.get('timings', {}).get('total', '—')}s",
        })
    st.dataframe(pd.DataFrame(history_data), use_container_width=True, hide_index=True)

    for i, r in enumerate(reports[:5]):
        label = (
            f"{r.get('timestamp', '')[:19]} — "
            f"{r.get('source_type', '').upper()} → {r.get('target_type', '').upper()} — "
            f"{r.get('table_name', '')} — "
            f"{'✅' if r.get('success') else '❌'}"
        )
        with st.expander(label):
            st.json({
                "source_type": r.get("source_type"),
                "target_type": r.get("target_type"),
                "table_name": r.get("table_name"),
                "transformations": r.get("transformations"),
                "validations": r.get("validations"),
                "executed_steps": r.get("executed_steps"),
                "success": r.get("success"),
                "timings": r.get("timings"),
                "output_file_path": r.get("output_file_path", "")
            })
else:
    st.caption("No historical runs yet. Run a migration to see results here.")