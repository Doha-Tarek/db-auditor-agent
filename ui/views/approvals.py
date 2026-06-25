# ui/views/approvals.py
# Review and approve/reject SQL remediation scripts.

import streamlit as st
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from agents.approval_agent import (
    show_pending_scripts,
    approve_script,
    reject_script_by_user,
    approve_all_safe,
    get_approval_summary
)


def _risk_badge(risk: str) -> str:
    colors = {
        "safe":        ("DCFCE7", "166534"),
        "moderate":    ("FEF3C7", "92400E"),
        "destructive": ("FEE2E2", "991B1B"),
    }
    bg, fg = colors.get(risk, ("F3F4F6", "374151"))
    return f'<span style="background:#{bg};color:#{fg};font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.04em">{risk}</span>'


def _status_badge(status: str) -> str:
    colors = {
        "pending":  ("FEF3C7", "92400E"),
        "executed": ("DCFCE7", "166534"),
        "rejected": ("FEE2E2", "991B1B"),
        "failed":   ("FEE2E2", "991B1B"),
    }
    bg, fg = colors.get(status, ("F3F4F6", "374151"))
    return f'<span style="background:#{bg};color:#{fg};font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.04em">{status}</span>'


def _severity_badge(severity: str) -> str:
    colors = {
        "critical": ("FEE2E2", "991B1B"),
        "high":     ("FEF3C7", "92400E"),
        "medium":   ("E0F2FE", "075985"),
        "low":      ("DCFCE7", "166534"),
    }
    bg, fg = colors.get(severity, ("F3F4F6", "374151"))
    return f'<span style="background:#{bg};color:#{fg};font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.04em">{severity}</span>'


def show(scan_run_id: str = None):

    st.markdown("""
    <style>
    section.main .block-container {
        padding: 2rem 2rem !important;
        max-width: 100% !important;
    }
    .card {
        background: #fff;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 20px 22px;
        margin-bottom: 12px;
    }
    .card-title {
        font-size: 13px;
        font-weight: 600;
        color: #111827;
        margin-bottom: 4px;
    }
    .card-sub {
        font-size: 12px;
        color: #6B7280;
        margin-bottom: 14px;
    }
    .meta-row {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-bottom: 12px;
        font-size: 12px;
        color: #6B7280;
    }
    .meta-item strong {
        color: #111827;
        font-weight: 500;
    }
    .sql-block {
        background: #1E293B;
        color: #94A3B8;
        font-family: 'Courier New', monospace;
        font-size: 12px;
        padding: 14px 16px;
        border-radius: 8px;
        white-space: pre-wrap;
        overflow-x: auto;
        margin-top: 10px;
        line-height: 1.6;
    }
    .info-row {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 13px;
        color: #374151;
        margin-bottom: 10px;
    }
    .info-row strong { color: #111827; }
    .stat-card {
        background: #fff;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 16px 18px;
    }
    .stat-label {
        font-size: 11px;
        font-weight: 600;
        color: #9CA3AF;
        text-transform: uppercase;
        letter-spacing: .06em;
        margin-bottom: 6px;
    }
    .stat-value {
        font-size: 26px;
        font-weight: 700;
        color: #111827;
        line-height: 1;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── header ─────────────────────────────────
    st.markdown("""
    <div style="padding:8px 0 24px">
        <h1 style="font-size:32px;font-weight:700;color:#2C3E50;
                   margin:0 0 6px;letter-spacing:-.02em">
            Remediation Script Approvals
        </h1>
        <p style="font-size:13px;color:#6B7280;margin:0">
            Review and approve SQL fix scripts before they are executed
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not scan_run_id:
        st.info("Select a scan from the sidebar first.")
        return

    # ── summary metrics ────────────────────────
    summary = get_approval_summary(scan_run_id)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Pending</div>
            <div class="stat-value" style="color:#D97706">{summary['pending']}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Executed</div>
            <div class="stat-value" style="color:#16A34A">{summary['executed']}</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Rejected</div>
            <div class="stat-value" style="color:#DC2626">{summary['rejected']}</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Safe scripts</div>
            <div class="stat-value" style="color:#16A34A">{summary['safe']}</div>
        </div>
        """, unsafe_allow_html=True)
    with col5:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Moderate scripts</div>
            <div class="stat-value" style="color:#D97706">{summary['moderate']}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── auto-approve safe ──────────────────────
    if summary["pending"] > 0 and summary["safe"] > 0:
        if st.button(
            f"Auto-approve all {summary['safe']} safe scripts",
            type="primary"
        ):
            result = approve_all_safe(scan_run_id, approved_by="ui_user")
            if result["executed"] > 0:
                st.success(result["message"])
            else:
                st.warning(result["message"])
            st.rerun()

    # ── filter ─────────────────────────────────
    st.markdown(
        "<div style='font-size:12px;font-weight:600;color:#6B7280;margin-bottom:6px'>Filter by status</div>",
        unsafe_allow_html=True
    )
    status_filter = st.selectbox(
        "status",
        ["pending", "executed", "rejected", "all"],
        index=0,
        label_visibility="collapsed"
    )

    # ── fetch scripts ──────────────────────────
    engine = get_audit_engine()
    with engine.connect() as conn:
        query = """
            SELECT
                rs.id, rs.sql_script, rs.risk_level,
                rs.explanation, rs.[rollback], rs.status,
                rs.confidence_score, rs.created_at,
                f.table_name, f.column_name,
                f.issue_type, f.severity,
                f.affected_rows
            FROM remediation_scripts rs
            JOIN findings f ON rs.finding_id = f.id
            WHERE f.scan_run_id = :scan_id
        """
        if status_filter != "all":
            query += " AND rs.status = :status"
        query += """
            ORDER BY
                CASE rs.risk_level
                    WHEN 'destructive' THEN 1
                    WHEN 'moderate'    THEN 2
                    WHEN 'safe'        THEN 3
                END
        """
        params = {"scan_id": scan_run_id}
        if status_filter != "all":
            params["status"] = status_filter

        scripts = conn.execute(text(query), params).fetchall()

    if not scripts:
        st.markdown(
            "<div style='color:#6B7280;font-size:14px;padding:20px 0'>No scripts found for this filter.</div>",
            unsafe_allow_html=True
        )
        return

    st.markdown(
        f"<div style='font-size:13px;color:#6B7280;margin:16px 0 12px'>{len(scripts)} scripts</div>",
        unsafe_allow_html=True
    )

    # ── render scripts ─────────────────────────
    for s in scripts:
        script_id   = str(s[0])
        sql_script  = s[1] or ""
        risk        = s[2] or "moderate"
        explanation = s[3] or ""
        rollback    = s[4] or ""
        status      = s[5] or "pending"
        table_name  = s[8] or ""
        col_name    = s[9] or ""
        issue_type  = s[10] or ""
        severity    = s[11] or ""
        affected    = s[12] or 0

        target = f"{table_name}.{col_name}" if col_name else table_name

        with st.expander(
            f"{risk.upper()} risk  —  {issue_type} in {target}  —  {affected} rows  —  {status.upper()}"
        ):
            # meta info
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown(f"""
                <div class="info-row">
                    <strong>Table:</strong> {table_name} &nbsp;·&nbsp;
                    <strong>Column:</strong> {col_name or '—'} &nbsp;·&nbsp;
                    <strong>Issue:</strong> {issue_type}
                </div>
                """, unsafe_allow_html=True)
            with col_r:
                st.markdown(f"""
                <div class="info-row">
                    {_risk_badge(risk)} &nbsp;
                    {_severity_badge(severity)} &nbsp;
                    {_status_badge(status)}
                    &nbsp;&nbsp; <strong>Rows affected:</strong> {affected}
                </div>
                """, unsafe_allow_html=True)

            if explanation:
                st.markdown(f"""
                <div style="font-size:13px;color:#374151;margin-bottom:8px">
                    <strong style="color:#111827">What this does:</strong> {explanation}
                </div>
                """, unsafe_allow_html=True)

            if rollback:
                st.markdown(f"""
                <div style="font-size:13px;color:#374151;margin-bottom:8px">
                    <strong style="color:#111827">Rollback:</strong> {rollback}
                </div>
                """, unsafe_allow_html=True)

            # SQL block
            st.markdown(
                f'<div class="sql-block">{sql_script}</div>',
                unsafe_allow_html=True
            )

            # approve / reject buttons
            if status == "pending":
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                btn1, btn2 = st.columns(2)

                with btn1:
                    if st.button(
                        "Approve and execute",
                        key=f"approve_{script_id}",
                        type="primary"
                    ):
                        with st.spinner("Executing..."):
                            result = approve_script(
                                script_id=script_id,
                                sql_script=sql_script,
                                approved_by="ui_user"
                            )
                        if result["success"]:
                            st.success(result["message"])
                        else:
                            st.error(result["message"])
                        st.rerun()

                with btn2:
                    if st.button(
                        "Reject",
                        key=f"reject_{script_id}"
                    ):
                        result = reject_script_by_user(
                            script_id=script_id,
                            rejected_by="ui_user",
                            reason="Rejected via UI"
                        )
                        st.warning(result["message"])
                        st.rerun()