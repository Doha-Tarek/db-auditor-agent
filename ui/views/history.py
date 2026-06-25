# ui/views/history.py
# Scan history and quality score trends — professional design.

import streamlit as st
from sqlalchemy import text
from tools.db_connector import get_audit_engine
import pandas as pd


def show():

    st.markdown("""
    <style>
    section.main .block-container { padding: 2rem 2rem !important; max-width: 100% !important; }

    .stat-card {
        background: #fff; border: 1px solid #E5E7EB;
        border-radius: 10px; padding: 16px 18px;
    }
    .stat-label {
        font-size: 11px; font-weight: 600; color: #9CA3AF;
        text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px;
    }
    .stat-value { font-size: 26px; font-weight: 700; color: #111827; line-height: 1; }
    .stat-sub   { font-size: 11px; color: #9CA3AF; margin-top: 4px; }

    .scan-card {
        background: #fff; border: 1px solid #E5E7EB;
        border-radius: 10px; padding: 16px 20px; margin-bottom: 10px;
    }
    .scan-header {
        display: flex; align-items: center;
        justify-content: space-between; margin-bottom: 12px;
    }
    .scan-date  { font-size: 13px; font-weight: 600; color: #111827; }
    .scan-db    { font-size: 12px; color: #6B7280; margin-top: 2px; }
    .scan-meta  {
        display: flex; gap: 24px; padding-top: 12px;
        border-top: 1px solid #F3F4F6; margin-top: 4px;
    }
    .scan-meta-item { font-size: 12px; color: #6B7280; }
    .scan-meta-item strong { font-size: 18px; font-weight: 700; color: #111827; display: block; }
    .scan-id    { font-size: 11px; color: #9CA3AF; font-family: monospace; margin-top: 8px; }

    .badge { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: .04em; }
    .badge-completed { background: #DCFCE7; color: #166534; }
    .badge-failed    { background: #FEE2E2; color: #991B1B; }
    .badge-running   { background: #FEF3C7; color: #92400E; }

    .score-pill {
        font-size: 20px; font-weight: 700; padding: 4px 14px;
        border-radius: 8px; display: inline-block;
    }
    .score-poor      { background: #FEE2E2; color: #DC2626; }
    .score-fair      { background: #FEF3C7; color: #D97706; }
    .score-good      { background: #DCFCE7; color: #16A34A; }
    .score-excellent { background: #DCFCE7; color: #15803D; }

    .section-title {
        font-size: 15px; font-weight: 600; color: #111827;
        margin: 28px 0 14px; border-bottom: 1px solid #E5E7EB; padding-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── header ─────────────────────────────────
    st.markdown("""
    <div style="padding:8px 0 24px">
        <div style="font-size:32px;font-weight:700;color:#2C3E50;
                    margin:0 0 6px;letter-spacing:-.02em;line-height:1.2">
            Scan History
        </div>
        <p style="font-size:13px;color:#6B7280;margin:0">
            Track data quality trends over time across all scan runs
        </p>
    </div>
    """, unsafe_allow_html=True)

    engine = get_audit_engine()
    with engine.connect() as conn:
        scans = conn.execute(text("""
            SELECT
                sr.id, sr.started_at, sr.completed_at,
                sr.overall_score, sr.total_findings,
                sr.critical_findings, sr.status,
                sr.triggered_by, dc.name AS db_name
            FROM scan_runs sr
            JOIN db_connections dc ON sr.connection_id = dc.id
            ORDER BY sr.started_at DESC
        """)).fetchall()

    if not scans:
        st.info("No scan history yet. Run your first scan with: python main.py")
        return

    completed = [s for s in scans if s[3] is not None and s[6] == "completed"]

    # ── top metrics ────────────────────────────
    if completed:
        latest_score  = int(completed[0][3])
        avg_score     = int(sum(s[3] for s in completed) / len(completed))
        total_scans   = len(scans)
        total_findings = sum(s[4] or 0 for s in completed)
        best_score    = int(max(s[3] for s in completed))
        worst_score   = int(min(s[3] for s in completed))

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        metrics = [
            (c1, "Latest score",    f"{latest_score}/100", None),
            (c2, "Average score",   f"{avg_score}/100",    None),
            (c3, "Best score",      f"{best_score}/100",   "#16A34A"),
            (c4, "Worst score",     f"{worst_score}/100",  "#DC2626"),
            (c5, "Total scans",     str(total_scans),      None),
            (c6, "Total findings",  str(total_findings),   None),
        ]

        for col, label, value, color in metrics:
            color_style = f"color:{color};" if color else ""
            col.markdown(f"""
            <div class="stat-card">
                <div class="stat-label">{label}</div>
                <div class="stat-value" style="{color_style}">{value}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── two charts side by side ────────────
        st.markdown('<div class="section-title">Quality trends</div>', unsafe_allow_html=True)

        chart_col1, chart_col2 = st.columns(2)

        # score trend
        df_score = pd.DataFrame({
            "Date":  [str(s[1])[:10] for s in completed],
            "Score": [int(s[3]) for s in completed]
        }).sort_values("Date")

        with chart_col1:
            st.markdown("""
            <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:8px">
                Quality score over time
            </div>
            """, unsafe_allow_html=True)
            st.line_chart(
                df_score.set_index("Date"),
                color="#2C3E50",
                height=200
            )

        # findings trend
        df_findings = pd.DataFrame({
            "Date":     [str(s[1])[:10] for s in completed],
            "Findings": [int(s[4] or 0) for s in completed]
        }).sort_values("Date")

        with chart_col2:
            st.markdown("""
            <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:8px">
                Total findings over time
            </div>
            """, unsafe_allow_html=True)
            st.bar_chart(
                df_findings.set_index("Date"),
                color="#E5E7EB",
                height=200
            )

    # ── scan list ──────────────────────────────
    st.markdown('<div class="section-title">All scans</div>', unsafe_allow_html=True)

    # split into two columns
    left_scans  = scans[::2]   # even index
    right_scans = scans[1::2]  # odd index

    col_l, col_r = st.columns(2)

    def _score_class(score):
        if score >= 90: return "score-excellent"
        if score >= 75: return "score-good"
        if score >= 50: return "score-fair"
        return "score-poor"

    def _status_badge(status):
        cls = {
            "completed": "badge-completed",
            "failed":    "badge-failed",
            "running":   "badge-running",
        }.get(status, "badge-completed")
        return f'<span class="badge {cls}">{status}</span>'

    def _render_scan_card(col, scan, key_suffix):
        score    = int(scan[3] or 0)
        total    = scan[4] or 0
        critical = scan[5] or 0
        status   = scan[6] or ""
        trigger  = scan[7] or ""
        db_name  = scan[8] or ""
        date     = str(scan[1])[:16] if scan[1] else "N/A"
        scan_id  = str(scan[0])

        with col:
            st.markdown(f"""
            <div class="scan-card">
                <div class="scan-header">
                    <div>
                        <div class="scan-date">{date}</div>
                        <div class="scan-db">{db_name}</div>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px">
                        {_status_badge(status)}
                        <span class="score-pill {_score_class(score)}">{score}</span>
                    </div>
                </div>
                <div class="scan-meta">
                    <div class="scan-meta-item">
                        <strong>{total}</strong>
                        Findings
                    </div>
                    <div class="scan-meta-item">
                        <strong style="color:#DC2626">{critical}</strong>
                        Critical
                    </div>
                    <div class="scan-meta-item">
                        <strong>{trigger}</strong>
                        Trigger
                    </div>
                </div>
                <div class="scan-id">ID: {scan_id[:8].upper()}</div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("View this scan", key=f"view_{scan_id}_{key_suffix}"):
                st.session_state.scan_run_id = scan_id
                st.session_state.page        = "dashboard"
                st.rerun()

    for i, scan in enumerate(left_scans):
        _render_scan_card(col_l, scan, f"l{i}")

    for i, scan in enumerate(right_scans):
        _render_scan_card(col_r, scan, f"r{i}")