"""
AI Data Migration Agent — Streamlit Dashboard

Includes:
1. PostgreSQL → MySQL Deterministic Migration (Demo)
2. LangGraph V2 Agentic Workflow (Observe → Analyze → Recommend → Review → Execute → Validate)
"""

import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime
import uuid
from dotenv import load_dotenv
load_dotenv()

from migration_service import start_migration, get_agent_state, resume_migration, run_migration

# ─────────────────────────────────────────────
# Page Config & Styles
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="AI Data Migration Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .dashboard-header {
        background: linear-gradient(135deg, #111827 0%, #374151 100%);
        padding: 1.8rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; color: white;
    }
    .section-header {
        font-size: 1.25rem; font-weight: 600; margin: 1.5rem 0 0.8rem 0;
        padding-bottom: 0.4rem; border-bottom: 2px solid rgba(108,99,255,0.3);
    }
    .badge {
        display: inline-block; padding: 0.2rem 0.6rem; border-radius: 12px;
        font-size: 0.8rem; font-weight: 600; background: rgba(108,99,255,0.1); color: #6C63FF;
    }
    .plan-card {
        background: rgba(102,126,234,0.05); border: 1px solid rgba(102,126,234,0.2);
        border-radius: 8px; padding: 1rem; margin-bottom: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session State Initialization
# ─────────────────────────────────────────────

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "workflow_started" not in st.session_state:
    st.session_state.workflow_started = False
if "workflow_finished" not in st.session_state:
    st.session_state.workflow_finished = False
if "demo_migration_result" not in st.session_state:
    st.session_state.demo_migration_result = None

# ─────────────────────────────────────────────
# Sidebar: Developer Mode & Reset
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🔑 API Configuration")
    st.caption("Leave blank to use Deterministic Fallback")
    
    provider_choice = st.selectbox("AI Provider", ["Gemini", "OpenAI"])
    api_key = st.text_input(f"{provider_choice} API Key", type="password")
    
    if api_key:
        if provider_choice == "Gemini":
            os.environ["GOOGLE_API_KEY"] = api_key
            if "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            st.success("✅ Gemini API Key Registered in Session!")
        else:
            os.environ["OPENAI_API_KEY"] = api_key
            if "GOOGLE_API_KEY" in os.environ:
                del os.environ["GOOGLE_API_KEY"]
            st.success("✅ OpenAI API Key Registered in Session!")
    else:
        # Clear keys to force fallback if empty
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    st.markdown("---")
    st.markdown("### 🛠️ Developer Options")
    dev_mode = st.toggle("Enable Developer Mode", value=False)
    
    if st.button("🔄 Reset Session", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.workflow_started = False
        st.session_state.workflow_finished = False
        st.session_state.demo_migration_result = None
        st.rerun()

st.markdown(
    '<div class="dashboard-header">'
    '<h1>🤖 AI Data Migration Consultant</h1>'
    '<p>PostgreSQL ➔ MySQL Migration Pipeline & Deterministic Data Cleaner</p>'
    '</div>',
    unsafe_allow_html=True
)

tab_demo, tab_agentic = st.tabs([
    "🚀 PostgreSQL → MySQL Migration (Demo)",
    "🤖 Agentic LangGraph Workflow (V2)"
])


# ═════════════════════════════════════════════
# TAB 1: PostgreSQL → MySQL Migration (Demo)
# ═════════════════════════════════════════════

with tab_demo:
    st.markdown('<div class="section-header">PostgreSQL → MySQL Deterministic Migration</div>', unsafe_allow_html=True)
    st.markdown("Extract data from **PostgreSQL**, apply **deterministic rule-based cleaning**, and load cleaned data into **MySQL**.")

    dataset_preset = st.radio(
        "📁 **Select Demo Dataset Preset:**",
        [
            "🛒 Messy E-Commerce Sales (103 rows)",
            "👥 Ultra-Dirty Employee & Payroll (130 rows — Max Dirt & 10 Rules Active)"
        ],
        horizontal=True,
        key="demo_dataset_preset"
    )

    default_src = "dirty_employees" if "Ultra-Dirty" in dataset_preset else "enterprise"
    default_tgt = f"{default_src}_migrated"

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🐘 PostgreSQL (Source)")
        source_table = st.text_input(
            "Source Table Name (PostgreSQL)",
            value=default_src,
            key=f"demo_src_tbl_{default_src}"
        )
    with col2:
        st.markdown("#### 🐬 MySQL (Target)")
        target_table = st.text_input(
            "Target Table Name (MySQL)",
            value=default_tgt,
            key=f"demo_tgt_tbl_{default_tgt}"
        )

    with st.expander("⚙️ Database Connection Settings (Environment Overrides)", expanded=False):
        c_pg, c_my = st.columns(2)
        with c_pg:
            st.markdown("##### PostgreSQL Credentials")
            pg_host = st.text_input("Host", value=os.environ.get("PG_HOST") or os.environ.get("DB_HOST", "127.0.0.1"), key="demo_pg_h")
            pg_port = st.number_input("Port", value=int(os.environ.get("PG_PORT") or os.environ.get("DB_PORT", 5432)), key="demo_pg_p")
            pg_db = st.text_input("Database", value=os.environ.get("PG_DATABASE") or os.environ.get("DB_DATABASE", "migration_db"), key="demo_pg_d")
            pg_user = st.text_input("User", value=os.environ.get("PG_USER") or os.environ.get("DB_USER", "postgres"), key="demo_pg_u")
            pg_pw = st.text_input("Password", value=os.environ.get("PG_PASSWORD") or os.environ.get("DB_PASSWORD", ""), type="password", key="demo_pg_pw")
        with c_my:
            st.markdown("##### MySQL Credentials")
            my_host = st.text_input("Host", value=os.environ.get("MYSQL_HOST", "127.0.0.1"), key="demo_my_h")
            my_port = st.number_input("Port", value=int(os.environ.get("MYSQL_PORT", 3306)), key="demo_my_p")
            my_db = st.text_input("Database", value=os.environ.get("MYSQL_DATABASE", "migration_db"), key="demo_my_d")
            my_user = st.text_input("User", value=os.environ.get("MYSQL_USER", "root"), key="demo_my_u")
            my_pw = st.text_input("Password", value=os.environ.get("MYSQL_PASSWORD", ""), type="password", key="demo_my_pw")

        st.markdown("---")
        if st.button("🌱 Populate Sample Tables in PostgreSQL (For Demo)", use_container_width=True, key="btn_seed_sample_pg"):
            try:
                from data.seed_postgres import seed_postgres
                # Set environment variables for host/port/creds if user edited them in the expander
                os.environ["PG_HOST"] = str(pg_host)
                os.environ["PG_PORT"] = str(pg_port)
                os.environ["PG_DATABASE"] = str(pg_db)
                os.environ["PG_USER"] = str(pg_user)
                os.environ["PG_PASSWORD"] = str(pg_pw)
                
                success = seed_postgres()
                if success:
                    st.success("✅ Successfully seeded BOTH 'enterprise' (103 rows) and 'dirty_employees' (130 rows) into PostgreSQL!")
                else:
                    st.warning("⚠️ Seeding completed with some warnings. Check logs.")
            except Exception as seed_err:
                st.error(f"❌ Could not seed PostgreSQL: {seed_err}")

    if st.button("🚀 Run Migration", type="primary", use_container_width=True, key="btn_run_demo_migration"):
        pg_config = {
            "host": pg_host,
            "port": int(pg_port),
            "database": pg_db,
            "username": pg_user,
            "password": pg_pw,
        }
        mysql_config = {
            "host": my_host,
            "port": int(my_port),
            "database": my_db,
            "username": my_user,
            "password": my_pw,
        }
        with st.spinner(f"Extracting '{source_table}' from PostgreSQL, cleaning data, and loading into MySQL '{target_table}'..."):
            res = run_migration(
                source_table=source_table,
                target_table=target_table,
                pg_config=pg_config,
                mysql_config=mysql_config
            )
            st.session_state.demo_migration_result = res

    res = st.session_state.get("demo_migration_result")
    if res:
        if res.get("status") == "success":
            st.success(
                f"✅ **Migration Successful!** "
                f"Source Rows: **{res.get('source_rows', 0)}** | Target Rows: **{res.get('target_rows', 0)}** | "
                f"Table: `{res.get('source_table')}` ➔ `{res.get('target_table')}`"
            )
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Source Rows Extracted", res.get("source_rows", 0))
            m2.metric("Target Rows Loaded", res.get("target_rows", 0))
            m3.metric("Transformations Applied", len(res.get("transformation_log", [])))
            m4.metric("Status", "SUCCESS")

            st.markdown('<div class="section-header">Transformation Log</div>', unsafe_allow_html=True)
            log_entries = res.get("transformation_log", [])
            if log_entries:
                st.dataframe(pd.DataFrame(log_entries), use_container_width=True, hide_index=True)
            else:
                st.info("No transformation steps recorded.")

            st.markdown('<div class="section-header">Before / After Data Preview (First 10 Rows)</div>', unsafe_allow_html=True)
            prev1, prev2 = st.columns(2)
            with prev1:
                st.markdown(f"**Raw Source Data (PostgreSQL: `{res.get('source_table')}`)**")
                if "source_preview" in res and isinstance(res["source_preview"], pd.DataFrame):
                    st.dataframe(res["source_preview"], use_container_width=True)
                else:
                    st.caption("No source preview data available.")
            with prev2:
                st.markdown(f"**Cleaned Target Data (MySQL: `{res.get('target_table')}`)**")
                if "target_preview" in res and isinstance(res["target_preview"], pd.DataFrame):
                    st.dataframe(res["target_preview"], use_container_width=True)
                else:
                    st.caption("No target preview data available.")

            # Live Target Database Verification Section
            st.markdown('<div class="section-header">Live Target Database Verification</div>', unsafe_allow_html=True)
            st.markdown(
                f"Data has been physically written into **MySQL** on host `{my_host}`, database `{my_db}`."
            )
            v1, v2 = st.columns([3, 1])
            with v1:
                st.info(f"✓ Target Table: `{res.get('target_table')}` | ✓ Verified Rows: **{res.get('target_rows', 0)}**")
            with v2:
                if "target_preview" in res and isinstance(res["target_preview"], pd.DataFrame):
                    csv_data = res["target_preview"].to_csv(index=False)
                    st.download_button(
                        "📥 Download Cleaned CSV",
                        data=csv_data,
                        file_name=f"{res.get('target_table')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

            with st.expander("🔍 Live Target Database Explorer (Query MySQL Directly)", expanded=False):
                try:
                    from connectors.mysql_connector import MySQLConnector
                    m_conn = MySQLConnector(**mysql_config)
                    tables = m_conn.list_tables()
                    st.write("**Tables in MySQL target database:**", tables)
                    if tables:
                        default_idx = tables.index(res.get('target_table')) if res.get('target_table') in tables else 0
                        chosen_tbl = st.selectbox("Select table to inspect directly from MySQL", options=tables, index=default_idx, key="sel_inspect_tbl")
                        if st.button("Query MySQL Table Live", key="btn_inspect_mysql"):
                            live_df = m_conn.read_data(chosen_tbl)
                            st.write(f"Live query result from MySQL `{chosen_tbl}` ({len(live_df)} rows):")
                            st.dataframe(live_df, use_container_width=True)
                except Exception as ex:
                    st.caption(f"Note: Live explorer connects using configured credentials ({ex})")
        else:
            st.error(f"❌ **Migration Failed:** {res.get('message', 'Database connection or migration error.')}")
            if res.get("transformation_log"):
                st.markdown("#### Partial Transformation Log")
                st.dataframe(pd.DataFrame(res["transformation_log"]), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════
# TAB 2: Agentic LangGraph Workflow (V2)
# ═════════════════════════════════════════════

with tab_agentic:
    # Section 1: Migration Request (Setup)
    if not st.session_state.workflow_started:
        st.markdown('<div class="section-header">1. Migration Request</div>', unsafe_allow_html=True)
        
        with st.container(border=True):
            st.markdown("#### 🤖 AI Configuration")
            ap_col1, ap_col2 = st.columns(2)
            with ap_col1:
                ai_provider = st.selectbox("AI Provider", ["Auto", "Groq", "Gemini", "OpenAI", "Deterministic"], key="v2_ai_prov")
            with ap_col2:
                model_options = [""]
                if ai_provider == "Groq":
                    model_options = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b"]
                elif ai_provider == "Gemini":
                    model_options = [
                        "gemini-2.5-flash",
                        "gemini-2.5-pro",
                        "gemini-2.5-flash-lite",
                        "gemini-2.0-flash",
                        "gemini-2.0-flash-lite",
                    ]
                elif ai_provider == "OpenAI":
                    model_options = ["gpt-4o"]
                ai_model = st.selectbox("AI Model", model_options, disabled=(ai_provider in ["Auto", "Deterministic"]), key="v2_ai_model")
                
            user_request = st.text_area("What is your migration goal?", placeholder="E.g., Migrate this MongoDB collection to PostgreSQL and clean the data.", key="v2_user_goal")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### 📥 Source")
                source_type = st.selectbox("Connector", ["CSV", "PostgreSQL", "MongoDB"], key="src_type")
                source_config = {}
                if source_type == "CSV":
                    uploaded_file = st.file_uploader("Upload CSV", type=["csv"], key="v2_csv_up")
                    if uploaded_file:
                        import tempfile
                        temp_dir = os.environ.get("DATA_DIR", tempfile.gettempdir())
                        os.makedirs(temp_dir, exist_ok=True)
                        file_path = os.path.join(temp_dir, uploaded_file.name)
                        with open(file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                        source_config = {"file_path": file_path}
                elif source_type == "PostgreSQL":
                    source_config = {
                        "host": st.text_input("Host", os.environ.get("PG_HOST") or os.environ.get("DB_HOST", "postgres.railway.internal"), key="s_pg_h"),
                        "port": st.number_input("Port", int(os.environ.get("PG_PORT") or os.environ.get("DB_PORT", "5432")), key="s_pg_p"),
                        "database": st.text_input("Database", os.environ.get("PG_DATABASE") or os.environ.get("DB_DATABASE", "railway"), key="s_pg_d"),
                        "username": st.text_input("User", os.environ.get("PG_USER") or os.environ.get("DB_USER", "postgres"), key="s_pg_u"),
                        "password": st.text_input("Password", os.environ.get("PG_PASSWORD") or os.environ.get("DB_PASSWORD", "xrmfThYabPbnYjqTEtsiyipXUGohdwFy"), type="password", key="s_pg_pw"),
                        "table_name": st.text_input("Table", "enterprise", key="s_pg_t")
                    }
                elif source_type == "MongoDB":
                    source_config = {
                        "connection_string": st.text_input("URI", os.environ.get("MONGO_URI", "mongodb://localhost:27017"), key="s_m_u"),
                        "database": st.text_input("Database", os.environ.get("DB_DATABASE", "migration_db"), key="s_m_d"),
                        "collection": st.text_input("Collection", "enterprise", key="s_m_c")
                    }

            with col2:
                st.markdown("#### 📤 Target")
                target_type = st.selectbox("Connector", ["DuckDB", "PostgreSQL", "MongoDB", "MySQL"], key="tgt_type")
                target_config = {}
                
                table_name = "enterprise_migrated"
                if source_type == "CSV" and "uploaded_file" in locals() and uploaded_file:
                    table_name = uploaded_file.name.split(".")[0]
                elif source_type in ("PostgreSQL", "MongoDB"):
                    table_name = source_config.get("table_name") or source_config.get("collection", "enterprise")
                    table_name += "_migrated"
                    
                table_name = st.text_input("Target Table/Collection Name", table_name, key="v2_tgt_tbl")
                
                if target_type == "DuckDB":
                    target_config = {"db_path": "migration.duckdb", "table_name": table_name}
                elif target_type == "PostgreSQL":
                    target_config = {
                        "host": st.text_input("Host", os.environ.get("PG_HOST") or os.environ.get("DB_HOST", "postgres.railway.internal"), key="t_pg_h"),
                        "port": st.number_input("Port", int(os.environ.get("PG_PORT") or os.environ.get("DB_PORT", "5432")), key="t_pg_p"),
                        "database": st.text_input("Database", os.environ.get("PG_DATABASE") or os.environ.get("DB_DATABASE", "railway"), key="t_pg_d"),
                        "username": st.text_input("User", os.environ.get("PG_USER") or os.environ.get("DB_USER", "postgres"), key="t_pg_u"),
                        "password": st.text_input("Password", os.environ.get("PG_PASSWORD") or os.environ.get("DB_PASSWORD", "xrmfThYabPbnYjqTEtsiyipXUGohdwFy"), type="password", key="t_pg_pw"),
                        "table_name": table_name
                    }
                elif target_type == "MySQL":
                    target_config = {
                        "host": st.text_input("Host", os.environ.get("MYSQL_HOST", "127.0.0.1"), key="t_my_h"),
                        "port": st.number_input("Port", int(os.environ.get("MYSQL_PORT", 3306)), key="t_my_p"),
                        "database": st.text_input("Database", os.environ.get("MYSQL_DATABASE", "migration_db"), key="t_my_d"),
                        "username": st.text_input("User", os.environ.get("MYSQL_USER", "root"), key="t_my_u"),
                        "password": st.text_input("Password", os.environ.get("MYSQL_PASSWORD", ""), type="password", key="t_my_pw"),
                        "table_name": table_name
                    }
                elif target_type == "MongoDB":
                    target_config = {
                        "connection_string": st.text_input("URI", os.environ.get("MONGO_URI", "mongodb://localhost:27017"), key="t_m_u"),
                        "database": st.text_input("Database", os.environ.get("DB_DATABASE", "migration_db"), key="t_m_d"),
                        "collection": table_name
                    }

            if st.button("🚀 Start Migration Assessment", use_container_width=True, type="primary"):
                initial_state = {
                    "query": user_request,
                    "ai_provider": ai_provider,
                    "ai_model": ai_model,
                    "source_type": source_type.lower(),
                    "target_type": target_type.lower(),
                    "source_config": source_config,
                    "target_config": target_config,
                    "table_name": table_name,
                    "plan_approved": False,
                    "executed_steps": [],
                    "timings": {}
                }
                try:
                    with st.spinner("Analyzing source data..."):
                        start_migration(st.session_state.thread_id, initial_state)
                    st.session_state.workflow_started = True
                    st.rerun()
                except Exception as e:
                    st.warning("⚠️ AI recommendations are currently unavailable — running in deterministic mode")
                    st.error(f"Workflow error: {e}")

    # Render Running / Completed State
    if st.session_state.workflow_started:
        try:
            snapshot = get_agent_state(st.session_state.thread_id)
        except Exception as e:
            st.warning("⚠️ AI recommendations are currently unavailable — running in deterministic mode")
            snapshot = None

        if not snapshot or not hasattr(snapshot, 'values'):
            st.warning("⚠️ AI recommendations are currently unavailable — running in deterministic mode")
            st.error("Could not retrieve agent state. Please use the deterministic migration tab or reset session.")
        else:
            state = snapshot.values
            next_nodes = snapshot.next
            
            is_paused = "human_review" in next_nodes
            is_finished = len(next_nodes) == 0
            st.session_state.workflow_finished = is_finished

            # ─── Section 2: Dataset Profile ───
            profile = state.get("profile", {})
            if profile:
                st.markdown('<div class="section-header">2. Dataset Profile</div>', unsafe_allow_html=True)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Rows", profile.get("row_count", 0))
                m2.metric("Columns", profile.get("column_count", 0))
                m3.metric("Duplicates", profile.get("duplicate_rows", 0))
                
                score = profile.get("data_quality_score", 0)
                score_color = "green" if score > 90 else "orange" if score > 70 else "red"
                m4.markdown(f"**Quality Score:** <span style='color:{score_color}; font-size:1.5rem'>{score}%</span>", unsafe_allow_html=True)
                
                with st.expander("Detailed Column Profiles"):
                    st.json(profile.get("columns", {}))

            # ─── Section 3: AI Assessment ───
            assessment = state.get("assessment", {})
            dsl = state.get("transformation_dsl", {})
            if assessment and dsl:
                st.markdown('<div class="section-header">3. AI Migration Assessment</div>', unsafe_allow_html=True)
                
                provider = dsl.get("planning_method", "unknown")
                
                if "fallback_reason" in dsl:
                    st.warning(f"⚠️ **AI recommendations are currently unavailable — running in deterministic mode**\n\n**Reason:** `{dsl['fallback_reason']}`")
                else:
                    st.caption(f"**AI Provider:** `{provider}`")
                
                st.info(f"**Assessment:**\n{assessment.get('dataset_assessment', '')}")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("#### 🚩 Issues")
                    for iss in assessment.get("identified_issues", []):
                        st.markdown(f"- {iss}")
                with c2:
                    st.markdown("#### 🗺️ Schema Mapping")
                    for map_rec in assessment.get("schema_mapping_recommendations", []):
                        st.markdown(f"- {map_rec}")

            # ─── Section 4: Transformation Plan & Impact ───
            if dsl:
                st.markdown('<div class="section-header">4. Transformation Plan & Impact</div>', unsafe_allow_html=True)
                
                impact = state.get("impact", {})
                if impact:
                    ic1, ic2, ic3, ic4 = st.columns(4)
                    ic1.metric("Rows", f"{impact.get('rows_before')} → {impact.get('rows_after')}")
                    ic2.metric("Duplicates Removed", impact.get("duplicates_removed", 0))
                    ic3.metric("Cols Changed", impact.get("columns_renamed", 0) + impact.get("columns_dropped", 0) + impact.get("columns_added", 0))
                    
                    qb = impact.get("quality_score_before", 0)
                    qa = impact.get("quality_score_after", 0)
                    diff = impact.get("improvement_pct", 0)
                    ic4.metric("Quality Score", f"{qa}%", f"{diff}%")
                    
                risk = state.get("risk", {})
                if risk:
                    st.markdown(f"**Migration Risk Assessment** (Confidence: {risk.get('overall_confidence')}%)")
                    with st.expander("Risk Classification"):
                        st.markdown(f"- **High Risk (<70%):** {', '.join(risk.get('high_risk', [])) or 'None'}")
                        st.markdown(f"- **Medium Risk (70-90%):** {', '.join(risk.get('medium_risk', [])) or 'None'}")
                        st.markdown(f"- **Low Risk (>90%):** {', '.join(risk.get('low_risk', [])) or 'None'}")

                transformations = dsl.get("transformations", [])
                reasoning_list = dsl.get("reasoning", [])
                previews = state.get("preview", [])
                
                if not transformations:
                    st.success("No transformations recommended. Data is clean!")
                else:
                    for idx, t in enumerate(transformations):
                        action = t.get("action")
                        column = t.get("column", "—")
                        
                        reason_str = "No reason provided."
                        if idx < len(reasoning_list) and "reason" in reasoning_list[idx]:
                            reason_str = reasoning_list[idx]["reason"]
                            
                        if "rejected_steps" not in st.session_state:
                            st.session_state.rejected_steps = set()
                            
                        with st.container(border=True):
                            col0, col1, col2 = st.columns([0.5, 2.5, 2])
                            
                            is_approved = col0.checkbox("Include", value=True, key=f"chk_{st.session_state.thread_id}_{idx}")
                            if not is_approved:
                                st.session_state.rejected_steps.add(idx)
                            elif idx in st.session_state.rejected_steps:
                                st.session_state.rejected_steps.remove(idx)
                                
                            confidence = t.get("confidence")
                            conf_str = f" 🟢 {confidence}%" if confidence else ""
                            if confidence and confidence < 70:
                                conf_str = f" 🔴 {confidence}% (High Risk)"
                            col1.markdown(f"**`{action}`**{conf_str}")
                            
                            if column != "—": col1.markdown(f"Target: `{column}`")
                            extras = [f"*{k}:* {v}" for k, v in t.items() if k not in ("action", "column", "confidence")]
                            if extras: col1.caption(" | ".join(extras))
                            
                            col2.markdown(f"*{reason_str}*")
                            
                            # Display Preview
                            if idx < len(previews):
                                preview_samples = previews[idx].get("samples", [])
                                if preview_samples:
                                    st.markdown("##### Transformation Preview")
                                    df_prev = pd.DataFrame(preview_samples)
                                    
                                    def highlight_diff(s):
                                        if s.name == 'before':
                                            return ['background-color: rgba(239, 68, 68, 0.15)'] * len(s)
                                        elif s.name == 'after':
                                            return ['background-color: rgba(16, 185, 129, 0.15)'] * len(s)
                                        return [''] * len(s)
                                        
                                    styled_df = df_prev.style.apply(highlight_diff, axis=0)
                                    st.dataframe(styled_df, use_container_width=True, hide_index=True)
                                else:
                                    st.caption("No sample changes detected for this step.")

            # ─── Section 5: Human Review (Only if paused) ───
            if is_paused:
                st.markdown('<div class="section-header">5. Human Review</div>', unsafe_allow_html=True)
                st.warning("✋ The AI has paused execution. Please review the preview and impact above.")
                
                feedback = st.text_input("Modify Plan (Optional)", placeholder="E.g., Keep duplicates, Cast column X to string")
                
                col1, col2, col3 = st.columns(3)
                if col1.button("✅ Approve Plan & Execute", use_container_width=True, type="primary"):
                    with st.spinner("Executing migration..."):
                        rej_list = list(st.session_state.get("rejected_steps", set()))
                        resume_migration(st.session_state.thread_id, plan_approved=True, human_feedback=feedback, rejected_steps=rej_list)
                    st.rerun()
                    
                if col2.button("🔄 Modify Plan & Re-Analyze", use_container_width=True):
                    if not feedback:
                        st.error("Please enter modification instructions first.")
                    else:
                        with st.spinner("Re-analyzing..."):
                            rej_list = list(st.session_state.get("rejected_steps", set()))
                            resume_migration(st.session_state.thread_id, plan_approved=False, human_feedback=feedback, rejected_steps=rej_list)
                        st.rerun()
                        
                if col3.button("❌ Reject Plan & Reset", use_container_width=True):
                    st.session_state.thread_id = str(uuid.uuid4())
                    st.session_state.workflow_started = False
                    st.session_state.workflow_finished = False
                    st.rerun()

            # ─── Section 6: Migration Execution Status ───
            if state.get("executed_steps"):
                st.markdown('<div class="section-header">6. Migration Execution Tracker</div>', unsafe_allow_html=True)
                steps_str = " → ".join([f"`{s}`" for s in state["executed_steps"]])
                st.markdown(steps_str)

            # ─── Section 7 & 8: Reconciliation & Final Report ───
            if is_finished:
                st.markdown('<div class="section-header">7. Migration Reconciliation</div>', unsafe_allow_html=True)
                recon_results = state.get("reconciliation", {})
                
                if state.get("success") and recon_results.get("overall_success"):
                    st.success("✅ Target Reachable and Migration Complete")
                else:
                    st.error("❌ Target Unreachable or No Rows Written (Rolled Back)")
                    
                r1, r2, r3 = st.columns(3)
                rows_read = recon_results.get("rows_read", 0)
                rows_written = recon_results.get("rows_written", 0)
                rows_skipped = recon_results.get("rows_skipped", 0)
                
                r1.metric("Rows Read (Source)", rows_read)
                r2.metric("Rows Written (Target)", rows_written)
                r3.metric("Discrepancy (Skipped)", rows_skipped)
                
                if rows_read > 0:
                    match_pct = round((rows_written / rows_read) * 100, 2)
                    st.progress(min(max(match_pct / 100.0, 0.0), 1.0), text=f"Data Transfer Completion: {match_pct}%")

                st.markdown('<div class="section-header">8. Executive Report</div>', unsafe_allow_html=True)
                report = state.get("report", {})
                
                st.markdown(f"### 🚀 {report.get('project_name', 'Migration Report')}")
                st.markdown(f"**Source:** `{report.get('source')}` ➡️ **Target:** `{report.get('target')}`")
                status_color = "#10B981" if report.get('success') else "#EF4444"
                status_text = "SUCCESS" if report.get('success') else "FAILED"
                st.markdown(f"**Final Status:** <span style='color:{status_color}; font-weight:bold;'>{status_text}</span>", unsafe_allow_html=True)
                
                st.markdown("#### 🤖 AI Execution Metadata")
                st.markdown(f"- **Provider Used:** `{report.get('provider_used', 'Unknown')}`")
                st.markdown(f"- **Model Used:** `{report.get('model_used', 'Unknown')}`")
                st.markdown(f"- **Fallback Used:** `{report.get('fallback_used', False)}`")
                if report.get('fallback_used'):
                    chain_str = ' ➡️ '.join(report.get('fallback_chain_traversed', []))
                    st.markdown(f"- **Fallback Chain:** `{chain_str}`")
                st.markdown(f"- **Assessment Provider:** `{report.get('assessment_provider', 'Unknown')}`")
                st.markdown(f"- **Transformation Provider:** `{report.get('transformation_provider', 'Unknown')}`")
                
                impact = report.get("impact", {})
                if impact:
                    st.markdown('<div class="section-header">11. 📈 Quality Breakdown</div>', unsafe_allow_html=True)
                    ic1, ic2 = st.columns(2)
                    qb = impact.get('quality_score_before', 0)
                    qa = impact.get('quality_score_after', 0)
                    diff = round(qa - qb, 2)
                    sign = "+" if diff >= 0 else ""
                    
                    ic1.metric("Data Quality Score", f"{qa}%", f"{sign}{diff}%")
                    ic2.metric("Total Rows Migrated", impact.get('rows_after'))
                    
                    st.markdown("**Forensics:**")
                    
                    parsing_induced_nulls = impact.get('parsing_induced_nulls', 0)
                    if parsing_induced_nulls > 0:
                        st.warning(f"⚠️ Parsing introduced {parsing_induced_nulls} new null values (e.g., unparseable text converted to NaN)")
                        
                    col1, col2 = st.columns(2)
                    mb = impact.get('missing_before', 0)
                    ma = impact.get('missing_after', 0)
                    col1.markdown(f"- **Missing Values:** `{mb}` ➡️ `{ma}`")
                    
                    db = impact.get('dupes_before', 0)
                    da = impact.get('dupes_after', 0)
                    col2.markdown(f"- **Duplicate Rows:** `{db}` ➡️ `{da}`")
                    
                    st.markdown("**Contributors:**")
                    if impact.get('duplicates_removed', 0):
                        st.markdown(f"✓ Duplicate rows removed: {impact.get('duplicates_removed')}")
                    if impact.get('missing_filled', 0):
                        st.markdown(f"✓ Missing values filled: {impact.get('missing_filled')}")
                    if impact.get('datetime_standardized', 0):
                        st.markdown(f"✓ Datetime columns standardized: {impact.get('datetime_standardized')}")
                    if impact.get('currency_parsed', 0):
                        st.markdown(f"✓ Currency columns parsed: {impact.get('currency_parsed')}")
                    if impact.get('fields_normalized', 0):
                        st.markdown(f"✓ Rating fields normalized: {impact.get('fields_normalized')}")
                    
                with st.expander("View Full Report Details"):
                    st.json(report)
                    
                json_report = json.dumps(report, indent=2)
                
                markdown_report = f"# {report.get('project_name', 'Migration Report')}\n\n"
                markdown_report += f"**Source:** `{report.get('source')}`\n"
                markdown_report += f"**Target:** `{report.get('target')}`\n"
                markdown_report += f"**Status:** {status_text}\n\n"
                markdown_report += f"## AI Execution Metadata\n"
                markdown_report += f"- Provider Used: `{report.get('provider_used', 'Unknown')}`\n"
                markdown_report += f"- Model Used: `{report.get('model_used', 'Unknown')}`\n"
                markdown_report += f"- Fallback Used: `{report.get('fallback_used', False)}`\n"
                if report.get('fallback_used'):
                    chain_str = ' -> '.join(report.get('fallback_chain_traversed', []))
                    markdown_report += f"- Fallback Chain: `{chain_str}`\n"
                markdown_report += f"- Assessment Provider: `{report.get('assessment_provider', 'Unknown')}`\n"
                markdown_report += f"- Transformation Provider: `{report.get('transformation_provider', 'Unknown')}`\n\n"
                markdown_report += f"## Impact\n"
                markdown_report += f"- Data Quality: {impact.get('quality_score_before')}% -> {impact.get('quality_score_after')}%\n"
                markdown_report += f"- Rows Migrated: {impact.get('rows_after')}\n"
                markdown_report += f"### Contributors\n"
                if impact.get('duplicates_removed', 0):
                    markdown_report += f"- Duplicate rows removed: {impact.get('duplicates_removed')}\n"
                if impact.get('missing_filled', 0):
                    markdown_report += f"- Missing values filled: {impact.get('missing_filled')}\n"
                if impact.get('datetime_standardized', 0):
                    markdown_report += f"- Datetime columns standardized: {impact.get('datetime_standardized')}\n"
                if impact.get('currency_parsed', 0):
                    markdown_report += f"- Currency columns parsed: {impact.get('currency_parsed')}\n"
                if impact.get('fields_normalized', 0):
                    markdown_report += f"- Rating fields normalized: {impact.get('fields_normalized')}\n"
                
                rc1, rc2 = st.columns(2)
                rc1.download_button("📥 Download JSON Report", data=json_report, file_name="migration_executive_report.json", mime="application/json", use_container_width=True)
                rc2.download_button("📥 Download Markdown Report", data=markdown_report, file_name="migration_executive_report.md", mime="text/markdown", use_container_width=True)
                
                target_type = state.get("target_type", "")
                if target_type == "duckdb" and report.get("success") and recon_results.get("overall_success"):
                    duckdb_path = state.get("target_config", {}).get("db_path", "migration.duckdb")
                    if os.path.exists(duckdb_path):
                        file_size_mb = os.path.getsize(duckdb_path) / (1024 * 1024)
                        st.markdown('<div class="section-header">📦 Download Migrated DuckDB Database</div>', unsafe_allow_html=True)
                        st.markdown(f"**Filename:** `{os.path.basename(duckdb_path)}` | **Size:** `{file_size_mb:.2f} MB`")
                        with open(duckdb_path, "rb") as f:
                            st.download_button("📥 Download DuckDB", data=f, file_name=os.path.basename(duckdb_path), mime="application/octet-stream", use_container_width=True, type="primary")

                if report.get('success') and recon_results.get("overall_success"):
                    st.balloons()
                    
            # ─── New Sections: AI Observability ───
            if state.get("transformation_dsl"):
                st.markdown('<div class="section-header">9. 🧠 AI Forensics</div>', unsafe_allow_html=True)
                st.markdown(f"- **Provider Used:** `{state.get('provider_used', 'Unknown')}`")
                st.markdown(f"- **Model Used:** `{state.get('model_used', 'Unknown')}`")
                st.markdown(f"- **Fallback Used:** `{state.get('fallback_used', False)}`")
                
                st.markdown("#### Raw Prompt")
                st.code(state.get("raw_prompt", ""), language="markdown")
                    
                st.markdown("#### Raw AI Response")
                st.code(state.get("raw_ai_response", ""), language="json")
                    
                st.markdown("#### Parsed DSL JSON")
                st.json(state.get("transformation_dsl", {}))
                    
                exec_log = state.get("execution_log", [])
                if exec_log:
                    st.markdown("#### Execution Log")
                    for log_item in exec_log:
                        action = log_item.get("action", "unknown")
                        status = log_item.get("status", "unknown")
                        if status == "success":
                            st.markdown(f"**{action}**: ✓ Success")
                        elif status == "skipped":
                            reason = log_item.get("reason", "Unknown reason")
                            st.markdown(f"**{action}**: ⚠ Skipped - Reason: {reason}")
                        else:
                            reason = log_item.get("details", {}).get("error", "Unknown error")
                            st.markdown(f"**{action}**: ✗ Failed - Reason: {reason}")
                            
                    quarantine = state.get("quarantine_report", [])
                    if quarantine:
                        with st.expander("⚠️ Data Quarantine Report", expanded=True):
                            for q in quarantine:
                                st.markdown(f"- **{q['column']}**: {q['rows_affected']} values could not be parsed by `{q['action']}` → became NaN. (Sample indices: {q.get('sample_indices', [])})")
                            
                    st.markdown('<div class="section-header">10. 📊 Transformation Coverage</div>', unsafe_allow_html=True)
                    recommended_steps = len(state.get("transformation_dsl", {}).get("transformations", []))
                    executed_steps = sum(1 for item in exec_log if item.get("status") == "success")
                    skipped_steps = sum(1 for item in exec_log if item.get("status") != "success")
                    coverage_pct = round((executed_steps / recommended_steps) * 100, 2) if recommended_steps else 100
                    
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("AI Recommended Steps", recommended_steps)
                    c2.metric("Executed Steps", executed_steps)
                    c3.metric("Skipped Steps", skipped_steps)
                    c4.metric("Coverage %", f"{coverage_pct}%")


# ─────────────────────────────────────────────
# Developer Mode Diagnostics
# ─────────────────────────────────────────────

if dev_mode and st.session_state.workflow_started:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### LangGraph Debug")
    try:
        debug_snap = get_agent_state(st.session_state.thread_id)
        if debug_snap and hasattr(debug_snap, "values"):
            st.sidebar.json({
                "next_nodes": debug_snap.next,
                "thread_id": st.session_state.thread_id,
                "executed_steps": debug_snap.values.get("executed_steps", [])
            })
            with st.sidebar.expander("Raw DSL Payload"):
                st.json(debug_snap.values.get("transformation_dsl", {}))
    except Exception as e:
        st.sidebar.error(f"Debug unavailable: {e}")
