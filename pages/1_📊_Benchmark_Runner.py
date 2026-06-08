"""
Benchmark Runner — Multi-Dataset SLA Compliance Testing

Run multiple datasets through the migration pipeline, measure
runtimes, validate results, and export benchmark reports.
"""

import streamlit as st
import pandas as pd
import os
import json
import time
from datetime import datetime

from graph import run_migration


# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Benchmark Runner",
    page_icon="📊",
    layout="wide"
)


# ─────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────

st.markdown("""
<style>
    .block-container {
        padding-top: 1.5rem;
    }

    .benchmark-header {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .benchmark-header h1 {
        margin: 0;
        font-size: 1.6rem;
        font-weight: 700;
    }
    .benchmark-header p {
        margin: 0.3rem 0 0 0;
        opacity: 0.85;
        font-size: 0.93rem;
    }

    .section-header {
        font-size: 1.15rem;
        font-weight: 600;
        margin-bottom: 0.8rem;
        padding-bottom: 0.4rem;
        border-bottom: 2px solid rgba(245, 87, 108, 0.3);
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────

if "benchmark_results" not in st.session_state:
    st.session_state.benchmark_results = None


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────

st.markdown("""
<div class="benchmark-header">
    <h1>📊 Benchmark Runner</h1>
    <p>Run multiple datasets through the migration pipeline and measure SLA compliance</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

col_config, col_spacer, col_info = st.columns([3, 0.3, 2])

with col_config:
    st.markdown(
        '<div class="section-header">'
        '⚙️ Benchmark Configuration</div>',
        unsafe_allow_html=True
    )

    uploaded_files = st.file_uploader(
        "Upload CSV Datasets",
        type=["csv"],
        accept_multiple_files=True,
        help="Upload one or more CSV files to benchmark"
    )

    sla_threshold = st.number_input(
        "SLA Threshold (seconds)",
        min_value=1.0,
        max_value=300.0,
        value=30.0,
        step=5.0,
        help="Maximum acceptable migration time per dataset"
    )

with col_info:
    st.markdown(
        '<div class="section-header">'
        'ℹ️ About</div>',
        unsafe_allow_html=True
    )

    st.markdown("""
    The Benchmark Runner executes the full
    migration pipeline on each uploaded dataset
    and collects:

    - ⏱️ **Per-step timings**
    - ✅ **Reconciliation results**
    - 📏 **Row counts**
    - 📊 **SLA compliance**

    Results can be exported as CSV for
    stakeholder reporting.
    """)


# ─────────────────────────────────────────────
# Run Benchmark
# ─────────────────────────────────────────────

if uploaded_files:
    st.markdown("---")

    st.info(f"📁 **{len(uploaded_files)} dataset(s)** loaded for benchmarking")

    run_btn = st.button(
        "🚀 Run Benchmark Suite",
        type="primary",
        use_container_width=True
    )

    if run_btn:
        results = []
        progress_bar = st.progress(0, text="Starting benchmark...")

        for i, file in enumerate(uploaded_files):
            progress_bar.progress(
                (i) / len(uploaded_files),
                text=f"Processing {file.name}..."
            )

            # Save file
            save_dir = "data"
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, file.name)
            with open(save_path, "wb") as f:
                f.write(file.getbuffer())

            table_name = (
                file.name
                .replace(".csv", "")
                .lower()
                .replace(" ", "_")
                .replace("-", "_")
            )

            # Run migration
            run_start = time.time()
            try:
                result = run_migration(
                    source_type="csv",
                    target_type="duckdb",
                    source_config={"file_path": save_path},
                    target_config={"db_path": "migration.duckdb", "table_name": table_name},
                    table_name=table_name
                )

                total_time = result.get("timings", {}).get("total", round(time.time() - run_start, 4))
                schema = result.get("schema", {})
                recon = result.get("reconciliation", {})

                results.append({
                    "Dataset": file.name,
                    "Rows": schema.get("row_count", 0),
                    "Columns": schema.get("column_count", 0),
                    "Target Reachable ✓": (
                        "✅" if recon.get("target_reachable", False) else "❌"
                    ),
                    "Table Created ✓": (
                        "✅" if recon.get("table_created", False) else "❌"
                    ),
                    "Status": (
                        "✅ Pass" if result.get("success")
                        else "❌ Fail"
                    ),
                    "Extract (s)": result.get("timings", {}).get("request_intake", "—"),
                    "Transform (s)": result.get("timings", {}).get("migration_executor", "—"),
                    "Reconcile (s)": result.get("timings", {}).get("reconciler", "—"),
                    "Total (s)": total_time,
                    "SLA": (
                        "✅ Within SLA"
                        if total_time <= sla_threshold
                        else "⚠️ Exceeds SLA"
                    ),
                })

            except Exception as e:
                results.append({
                    "Dataset": file.name,
                    "Rows": "—",
                    "Columns": "—",
                    "Target Reachable ✓": "—",
                    "Table Created ✓": "—",
                    "Status": f"❌ Error",
                    "Extract (s)": "—",
                    "Transform (s)": "—",
                    "Reconcile (s)": "—",
                    "Total (s)": "—",
                    "SLA": "—",
                })

        progress_bar.progress(1.0, text="Benchmark complete!")
        st.session_state.benchmark_results = results


# ─────────────────────────────────────────────
# Display Results
# ─────────────────────────────────────────────

if st.session_state.benchmark_results:
    results = st.session_state.benchmark_results
    results_df = pd.DataFrame(results)

    st.markdown("---")
    st.markdown(
        '<div class="section-header">'
        '📊 Benchmark Results</div>',
        unsafe_allow_html=True
    )

    # Summary metrics
    total = len(results)
    passed = sum(
        1 for r in results if r["Status"] == "✅ Pass"
    )
    failed = total - passed
    sla_met = sum(
        1 for r in results if r["SLA"] == "✅ Within SLA"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Datasets", total)
    m2.metric("Passed", passed)
    m3.metric("Failed", failed)
    m4.metric("SLA Compliant", f"{sla_met}/{total}")

    st.markdown("")

    # Results table
    st.dataframe(
        results_df,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    # Export
    col_export1, col_export2, col_spacer = st.columns([1, 1, 2])

    with col_export1:
        csv_data = results_df.to_csv(index=False)
        st.download_button(
            "📥 Export as CSV",
            data=csv_data,
            file_name=(
                f"benchmark_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                f".csv"
            ),
            mime="text/csv",
            use_container_width=True
        )

    with col_export2:
        json_data = json.dumps(results, indent=2, default=str)
        st.download_button(
            "📥 Export as JSON",
            data=json_data,
            file_name=(
                f"benchmark_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                f".json"
            ),
            mime="application/json",
            use_container_width=True
        )
