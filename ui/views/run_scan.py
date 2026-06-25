# ui/views/run_scan.py
# Trigger a new scan from the UI.

import streamlit as st
import subprocess
import sys
from pathlib import Path


def show():

    st.markdown("""
    <style>
    section.main .block-container { padding: 2rem 2rem !important; max-width: 100% !important; }

    .step-card {
        background: #fff;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 10px;
        display: flex;
        align-items: flex-start;
        gap: 16px;
    }
    .step-number {
        width: 28px; height: 28px;
        background: #2C3E50;
        color: #fff;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 12px; font-weight: 700;
        flex-shrink: 0;
    }
    .step-body { flex: 1; }
    .step-title {
        font-size: 13px; font-weight: 600;
        color: #111827; margin-bottom: 2px;
    }
    .step-desc { font-size: 12px; color: #6B7280; }

    .info-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
    .info-card p {
        font-size: 13px;
        color: #374151;
        margin: 0;
        line-height: 1.6;
    }

    .result-card {
        background: #fff;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 20px;
        margin-top: 20px;
        font-family: 'Courier New', monospace;
        font-size: 12px;
        color: #374151;
        white-space: pre-wrap;
        line-height: 1.6;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── header ─────────────────────────────────
    st.markdown("""
    <div style="padding:8px 0 24px">
        <div style="font-size:32px;font-weight:700;color:#2C3E50;
                    margin:0 0 6px;letter-spacing:-.02em;line-height:1.2">
            Run New Scan
        </div>
        <p style="font-size:13px;color:#6B7280;margin:0">
            Trigger a full data quality scan against your connected database
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── info box ────────────────────────────────
    st.markdown("""
    <div class="info-card">
        <p>
            The scan pipeline runs automatically in 5 steps.
            This may take 1–2 minutes depending on database size and LLM response time.
            Do not close this window while the scan is running.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── steps ───────────────────────────────────
    steps = [
        (
            "Schema Inspection",
            "Connects to the target database and reads all table structures, columns, data types and row counts."
        ),
        (
            "Data Quality Scanning",
            "Runs checks for null values, duplicate rows, statistical outliers and orphan foreign keys across all tables."
        ),
        (
            "AI Analysis",
            "Sends findings to the LLM which explains each issue, identifies root causes and assigns business impact scores."
        ),
        (
            "Report Generation",
            "Generates a professional HTML and PDF report summarising all findings with the AI analysis included."
        ),
        (
            "Remediation Script Generation",
            "Generates SQL fix scripts for each finding. Scripts are saved for human review and are never executed automatically."
        ),
    ]

    for i, (title, desc) in enumerate(steps, 1):
        st.markdown(f"""
        <div class="step-card">
            <div class="step-number">{i}</div>
            <div class="step-body">
                <div class="step-title">{title}</div>
                <div class="step-desc">{desc}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── scan button ─────────────────────────────
    if st.button("Start full scan", type="primary"):
        with st.spinner("Running full scan pipeline — please wait..."):
            try:
                root   = Path(__file__).resolve().parent.parent.parent
                result = subprocess.run(
                    [sys.executable, str(root / "main.py")],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=str(root)
                )

                if result.returncode == 0:
                    st.success("Scan completed successfully.")
                    st.markdown(
                        f'<div class="result-card">{result.stdout}</div>',
                        unsafe_allow_html=True
                    )
                    st.session_state.page = "dashboard"
                    st.rerun()
                else:
                    st.error("Scan failed — see error output below.")
                    st.markdown(
                        f'<div class="result-card" style="border-color:#FEE2E2;color:#991B1B">'
                        f'{result.stderr}</div>',
                        unsafe_allow_html=True
                    )

            except Exception as e:
                st.error(f"Could not start scan: {e}")

    # ── last scan info ──────────────────────────
    try:
        from tools.db_connector import get_audit_engine
        from sqlalchemy import text

        engine = get_audit_engine()
        with engine.connect() as conn:
            last = conn.execute(text("""
                SELECT TOP 1 started_at, overall_score,
                             total_findings, status
                FROM scan_runs
                ORDER BY started_at DESC
            """)).fetchone()

        if last:
            score  = int(last[1] or 0)
            total  = last[2] or 0
            status = last[3] or ""
            date   = str(last[0])[:16] if last[0] else "N/A"

            score_color = (
                "#DC2626" if score < 50 else
                "#D97706" if score < 75 else
                "#16A34A"
            )

            st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
            st.markdown(f"""
            <div style="background:#fff;border:1px solid #E5E7EB;border-radius:10px;
                        padding:16px 20px">
                <div style="font-size:11px;font-weight:600;color:#9CA3AF;
                            text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px">
                    Last scan
                </div>
                <div style="display:flex;gap:32px;flex-wrap:wrap">
                    <div>
                        <div style="font-size:11px;color:#6B7280;margin-bottom:2px">Date</div>
                        <div style="font-size:14px;font-weight:500;color:#111827">{date}</div>
                    </div>
                    <div>
                        <div style="font-size:11px;color:#6B7280;margin-bottom:2px">Score</div>
                        <div style="font-size:14px;font-weight:700;color:{score_color}">{score}/100</div>
                    </div>
                    <div>
                        <div style="font-size:11px;color:#6B7280;margin-bottom:2px">Findings</div>
                        <div style="font-size:14px;font-weight:500;color:#111827">{total}</div>
                    </div>
                    <div>
                        <div style="font-size:11px;color:#6B7280;margin-bottom:2px">Status</div>
                        <div style="font-size:14px;font-weight:500;color:#111827">{status.title()}</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    except Exception:
        pass