"""
AI Data Migration Agent — Dashboard

Professional operational console for running, monitoring, and
reviewing data migrations powered by the LangGraph agent workflow.
"""

import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime

from migration_service import run_full_migration, load_reports
from connectors.duckdb_connector import DuckDBConnector


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
    /* ---- Global ---- */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    /* ---- Header ---- */
    .dashboard-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.8rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .dashboard-header h1 {
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .dashboard-header p {
        margin: 0.3rem 0 0 0;
        opacity: 0.85;
        font-size: 0.95rem;
    }

    /* ---- Pipeline Step ---- */
    .step-card {
        padding: 0.7rem 1rem;
        margin: 0.35rem 0;
        border-radius: 8px;
        display: flex;
        align-items: center;
        gap: 0.6rem;
        font-size: 0.95rem;
        font-weight: 500;
    }
    .step-pass {
        background: rgba(0, 217, 126, 0.10);
        border-left: 4px solid #00D97E;
        color: #00D97E;
    }
    .step-fail {
        background: rgba(230, 55, 87, 0.10);
        border-left: 4px solid #E63757;
        color: #E63757;
    }
    .step-pending {
        background: rgba(149, 170, 201, 0.08);
        border-left: 4px solid #95AAC9;
        color: #95AAC9;
    }

    /* ---- Validation Badge ---- */
    .validation-pass {
        color: #00D97E;
        font-weight: 600;
        font-size: 1.05rem;
    }
    .validation-fail {
        color: #E63757;
        font-weight: 600;
        font-size: 1.05rem;
    }

    /* ---- Section Header ---- */
    .section-header {
        font-size: 1.15rem;
        font-weight: 600;
        margin-bottom: 0.8rem;
        padding-bottom: 0.4rem;
        border-bottom: 2px solid rgba(108, 99, 255, 0.3);
    }

    /* ---- Sidebar ---- */
    section[data-testid="stSidebar"] > div {
        padding-top: 1.5rem;
    }

    /* ---- Metric styling ---- */
    [data-testid="stMetricValue"] {
        font-size: 1.3rem;
    }

    /* ---- History card ---- */
    .history-row {
        padding: 0.6rem 0.8rem;
        margin: 0.25rem 0;
        border-radius: 6px;
        background: rgba(108, 99, 255, 0.05);
        border-left: 3px solid #667eea;
        font-size: 0.88rem;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session State Initialization
# ─────────────────────────────────────────────

if "migration_result" not in st.session_state:
    st.session_state.migration_result = None
if "migration_ran" not in st.session_state:
    st.session_state.migration_ran = False


# ─────────────────────────────────────────────
# Supported Connectors
# ─────────────────────────────────────────────

SOURCE_CONNECTORS = {
    "CSV": {"extensions": ["csv"], "ready": True},
    "PostgreSQL": {"extensions": [], "ready": False},
    "MongoDB": {"extensions": [], "ready": False},
    "Parquet": {"extensions": ["parquet"], "ready": False},
}

TARGET_CONNECTORS = {
    "DuckDB": {"ready": True},
    "PostgreSQL": {"ready": False},
    "Snowflake": {"ready": False},
    "BigQuery": {"ready": False},
}


# ─────────────────────────────────────────────
# Sidebar — Migration Configuration
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Migration Configuration")
    st.markdown("---")

    # Source type
    source_options = list(SOURCE_CONNECTORS.keys())
    source_type = st.selectbox(
        "Source Connector",
        source_options,
        format_func=lambda x: f"{'✅' if SOURCE_CONNECTORS[x]['ready'] else '🔒'} {x}"
    )

    if not SOURCE_CONNECTORS[source_type]["ready"]:
        st.warning(f"{source_type} connector coming soon")

    # Target type
    target_options = list(TARGET_CONNECTORS.keys())
    target_type = st.selectbox(
        "Target Connector",
        target_options,
        format_func=lambda x: f"{'✅' if TARGET_CONNECTORS[x]['ready'] else '🔒'} {x}"
    )

    if not TARGET_CONNECTORS[target_type]["ready"]:
        st.warning(f"{target_type} connector coming soon")

    st.markdown("---")

    # File Upload
    allowed_extensions = SOURCE_CONNECTORS.get(source_type, {}).get("extensions", ["csv"])
    uploaded_file = st.file_uploader(
        "📁 Upload Source File",
        type=allowed_extensions if allowed_extensions else ["csv"]
    )

    st.markdown("---")

    # Run button
    connectors_ready = (
        SOURCE_CONNECTORS.get(source_type, {}).get("ready", False) and
        TARGET_CONNECTORS.get(target_type, {}).get("ready", False)
    )

    run_disabled = not (uploaded_file and connectors_ready)
    run_migration_btn = st.button(
        "🚀 Run Migration",
        type="primary",
        use_container_width=True,
        disabled=run_disabled
    )

    if run_disabled and not uploaded_file:
        st.caption("Upload a file to enable migration")

    st.markdown("---")
    st.markdown("### 📜 Quick Info")
    st.caption(
        "**Workflow:** Planner → Retriever → "
        "Executor → Tester → Supervisor"
    )
    st.caption("**Engine:** LangGraph StateGraph")
    st.caption(
        "**Validations:** Row Count · Checksum"
    )


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────

st.markdown("""
<div class="dashboard-header">
    <h1>🔄 AI Data Migration Console</h1>
    <p>Operational dashboard for agent-driven data migrations</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Execute Migration
# ─────────────────────────────────────────────

if run_migration_btn and uploaded_file:

    # Save uploaded file to data/
    save_dir = "data"
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, uploaded_file.name)
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # Derive table name from filename
    table_name = (
        uploaded_file.name
        .replace(".csv", "")
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    # Run migration
    with st.spinner("⏳ Running migration pipeline..."):
        try:
            result = run_full_migration(
                source_type=source_type,
                target_type=target_type,
                source_path=save_path,
                db_path="migration.duckdb",
                table_name=table_name
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

    # ─── Top Banner ───
    if success:
        st.success("✅ Migration completed successfully")
    else:
        st.error("❌ Migration failed — rollback executed")

    # ─── Row 1: Pipeline + Validation ───
    col_pipeline, col_spacer, col_validation = st.columns([3, 0.3, 2])

    with col_pipeline:
        st.markdown(
            '<div class="section-header">'
            '📊 Pipeline Status</div>',
            unsafe_allow_html=True
        )

        pipeline_steps = [
            ("Extract", "extract"),
            ("Transform", "transform"),
            ("Load", "load"),
            ("Validate", "validate")
        ]

        for label, key in pipeline_steps:
            is_done = key in executed_steps or key == "validate"
            step_time = timings.get(key, None)
            time_str = f"  —  {step_time}s" if step_time else ""

            if is_done and (key != "validate" or success):
                css = "step-pass"
                icon = "✅"
            elif is_done and key == "validate" and not success:
                css = "step-fail"
                icon = "❌"
            else:
                css = "step-pending"
                icon = "⏳"

            st.markdown(
                f'<div class="step-card {css}">'
                f'{icon} {label}{time_str}</div>',
                unsafe_allow_html=True
            )

    with col_validation:
        st.markdown(
            '<div class="section-header">'
            '🛡️ Validation Results</div>',
            unsafe_allow_html=True
        )

        row_count_ok = validation.get("row_count", False)
        checksum_ok = validation.get("checksum", False)
        overall_ok = validation.get("overall_success", False)

        checks = [
            ("Row Count Validation", row_count_ok),
            ("Checksum Validation", checksum_ok),
            ("Overall Migration", overall_ok),
        ]

        for label, passed in checks:
            css = "validation-pass" if passed else "validation-fail"
            icon = "✅" if passed else "❌"
            st.markdown(
                f'<div class="{css}">{icon}  {label}</div>',
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ─── Row 2: Timing Metrics ───
    st.markdown(
        '<div class="section-header">'
        '⏱️ Timing Metrics</div>',
        unsafe_allow_html=True
    )

    m1, m2, m3, m4, m5 = st.columns(5)

    m1.metric(
        "Extract",
        f"{timings.get('extract', '—')}s"
    )
    m2.metric(
        "Transform",
        f"{timings.get('transform', '—')}s"
    )
    m3.metric(
        "Load",
        f"{timings.get('load', '—')}s"
    )
    m4.metric(
        "Validate",
        f"{timings.get('validate', '—')}s"
    )
    m5.metric(
        "Total",
        f"{timings.get('total', '—')}s"
    )

    st.markdown("---")

    # ─── Row 3: Schema Discovery ───
    st.markdown(
        '<div class="section-header">'
        '🔍 Schema Discovery</div>',
        unsafe_allow_html=True
    )

    s1, s2, s3 = st.columns(3)
    s1.metric("Row Count", f"{schema.get('row_count', 0):,}")
    s2.metric("Column Count", schema.get("column_count", 0))

    pk_candidates = schema.get("primary_key_candidates", [])
    s3.metric(
        "Primary Key Candidates",
        ", ".join(pk_candidates) if pk_candidates else "None"
    )

    columns_data = schema.get("columns", [])
    if columns_data:
        schema_df = pd.DataFrame(columns_data)
        schema_df.columns = [
            "Column Name", "Data Type", "Nullable", "Unique"
        ]
        st.dataframe(
            schema_df,
            use_container_width=True,
            hide_index=True
        )

    st.markdown("---")

    # ─── Row 4: Data Preview ───
    with st.expander("📋 Data Preview", expanded=False):

        preview_col1, preview_col2 = st.columns(2)

        with preview_col1:
            st.markdown("**Source Data** (first 10 rows)")
            source_path = report.get("source_path", "")
            if source_path and os.path.exists(source_path):
                source_preview = pd.read_csv(source_path, nrows=10)
                st.dataframe(
                    source_preview,
                    use_container_width=True,
                    hide_index=True
                )

        with preview_col2:
            st.markdown("**Target Data** (first 10 rows)")
            try:
                target = DuckDBConnector(
                    report.get("db_path", "migration.duckdb"),
                    report.get("table_name", "enterprise")
                )
                target_df = target.read_data()
                st.dataframe(
                    target_df.head(10),
                    use_container_width=True,
                    hide_index=True
                )
            except Exception:
                st.info("Target table not available for preview")

    # ─── Row 5: Migration Report ───
    with st.expander("📄 Migration Report", expanded=False):

        report_display = {
            "Timestamp": report.get("timestamp", ""),
            "Source Type": report.get("source_type", ""),
            "Target Type": report.get("target_type", ""),
            "Source Path": report.get("source_path", ""),
            "Table Name": report.get("table_name", ""),
            "Executed Steps": report.get("executed_steps", []),
            "Success": report.get("success", False),
            "Validation Results": report.get("validation_results", {}),
            "Timings": report.get("timings", {})
        }

        st.json(report_display)

        report_json = json.dumps(report_display, indent=2, default=str)
        st.download_button(
            "📥 Download Report JSON",
            data=report_json,
            file_name=f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

else:

    # ─── Empty State ───
    st.markdown("---")

    empty1, empty2, empty3 = st.columns([1, 2, 1])

    with empty2:
        st.markdown(
            """
            <div style="text-align: center; padding: 3rem 0; opacity: 0.6;">
                <p style="font-size: 3rem; margin-bottom: 0.5rem;">📂</p>
                <p style="font-size: 1.1rem; font-weight: 500;">
                    Upload a dataset and run migration
                </p>
                <p style="font-size: 0.9rem;">
                    Use the sidebar to configure source & target connectors
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────
# Historical Runs
# ─────────────────────────────────────────────

st.markdown("---")
st.markdown(
    '<div class="section-header">'
    '📜 Historical Runs</div>',
    unsafe_allow_html=True
)

reports = load_reports()

if reports:
    history_data = []
    for r in reports:
        history_data.append({
            "Timestamp": r.get("timestamp", "")[:19],
            "Source": r.get("source_type", ""),
            "Target": r.get("target_type", ""),
            "Table": r.get("table_name", ""),
            "Status": "✅ Pass" if r.get("success") else "❌ Fail",
            "Total Time": f"{r.get('timings', {}).get('total', '—')}s",
        })

    st.dataframe(
        pd.DataFrame(history_data),
        use_container_width=True,
        hide_index=True
    )

    # Detail expander for each report
    for i, r in enumerate(reports[:5]):
        label = (
            f"{r.get('timestamp', '')[:19]} — "
            f"{r.get('table_name', '')} — "
            f"{'✅' if r.get('success') else '❌'}"
        )
        with st.expander(label):
            st.json({
                "source_type": r.get("source_type"),
                "target_type": r.get("target_type"),
                "table_name": r.get("table_name"),
                "executed_steps": r.get("executed_steps"),
                "success": r.get("success"),
                "validation_results": r.get("validation_results"),
                "timings": r.get("timings")
            })
else:
    st.caption("No historical runs yet. Run a migration to see results here.")