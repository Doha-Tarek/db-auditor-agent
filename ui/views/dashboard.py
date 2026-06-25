# ui/views/dashboard.py
import streamlit as st
from sqlalchemy import text
from tools.db_connector import get_audit_engine


def _badge(severity):
    colors = {
        "critical": ("FEE2E2", "991B1B"),
        "high":     ("FEF3C7", "92400E"),
        "medium":   ("E0F2FE", "075985"),
        "low":      ("DCFCE7", "166534"),
    }
    bg, fg = colors.get(severity, ("F3F4F6", "374151"))
    return f'<span style="background:#{bg};color:#{fg};font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;text-transform:uppercase">{severity}</span>'


def show(scan_run_id: str = None):

    st.markdown("""
    <style>
    section.main .block-container{padding:2rem 2rem 2rem !important;max-width:100%!important}
    .metric-container{background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:16px 18px;margin-bottom:0}
    .m-lbl{font-size:11px;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
    .m-val{font-size:26px;font-weight:700;line-height:1}
    .m-sub{font-size:11px;color:#9CA3AF;margin-top:4px}
    .card{background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:20px 22px}
    .card-title{font-size:13px;font-weight:600;color:#111827;margin-bottom:16px}
    .bar-label-row{display:flex;justify-content:space-between;font-size:12px;color:#374151;margin-bottom:5px}
    .bar-track{background:#F3F4F6;border-radius:4px;height:6px;margin-bottom:11px}
    .bar-fill{height:6px;border-radius:4px}
    .finding-row{display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid #F9FAFB}
    .finding-row:last-child{border-bottom:none}
    .finding-left{display:flex;align-items:center;gap:10px}
    .finding-icon{width:30px;height:30px;border-radius:6px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
    .fi-null{background:#FEF3C7}.fi-dup{background:#DBEAFE}.fi-outlier{background:#EDE9FE}.fi-fk{background:#FEE2E2}
    .finding-name{font-size:13px;font-weight:500;color:#111827}
    .finding-count{font-size:11px;color:#6B7280;margin-top:1px}
    .pill{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#6B7280;background:#F9FAFB;border:1px solid #E5E7EB;border-radius:20px;padding:4px 12px;margin-right:8px}
    .dot{width:6px;height:6px;border-radius:50%;background:#22C55E;display:inline-block}
    .findings-tbl{width:100%;border-collapse:collapse;font-size:12px}
    .findings-tbl th{text-align:left;color:#9CA3AF;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:0 0 8px;border-bottom:1px solid #E5E7EB}
    .findings-tbl td{padding:9px 0;border-bottom:1px solid #F9FAFB;color:#374151;vertical-align:middle}
    .findings-tbl tr:last-child td{border-bottom:none}
    .tbl-t{font-weight:500;color:#111827}.tbl-c{color:#6B7280}
    </style>
    """, unsafe_allow_html=True)

    if not scan_run_id:
        st.info("Select a scan from the sidebar to view results.")
        return

    engine = get_audit_engine()
    with engine.connect() as conn:

        scan = conn.execute(text("""
            SELECT sr.started_at, sr.completed_at, sr.overall_score,
                   sr.total_findings, sr.critical_findings, sr.status,
                   dc.name AS db_name
            FROM scan_runs sr
            JOIN db_connections dc ON sr.connection_id = dc.id
            WHERE sr.id = :sid
        """), {"sid": scan_run_id}).fetchone()

        if not scan:
            st.error("Scan not found.")
            return

        score        = int(scan[2] or 0)
        total        = scan[3] or 0
        critical_cnt = scan[4] or 0
        db_name      = scan[6]
        scan_date    = str(scan[0])[:16] if scan[0] else "N/A"

        duration = "N/A"
        if scan[0] and scan[1]:
            secs     = int((scan[1] - scan[0]).total_seconds())
            duration = f"{secs}s" if secs < 60 else f"{secs//60}m {secs%60}s"

        short_id = scan_run_id[:8].upper()

        sev_rows = conn.execute(text("""
            SELECT severity, COUNT(*) FROM findings
            WHERE scan_run_id = :sid GROUP BY severity
        """), {"sid": scan_run_id}).fetchall()
        sev = {r[0]: r[1] for r in sev_rows}

        type_rows = conn.execute(text("""
            SELECT issue_type, COUNT(*) AS cnt FROM findings
            WHERE scan_run_id = :sid
            GROUP BY issue_type ORDER BY cnt DESC
        """), {"sid": scan_run_id}).fetchall()

        findings_rows = conn.execute(text("""
            SELECT table_name, column_name, issue_type,
                   severity, affected_rows, affected_percent
            FROM findings WHERE scan_run_id = :sid
            ORDER BY CASE severity
                WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                WHEN 'medium'   THEN 3 WHEN 'low'  THEN 4
            END, table_name
        """), {"sid": scan_run_id}).fetchall()

        all_findings = [
            {"table_name": r[0], "column_name": r[1], "issue_type": r[2],
             "severity": r[3], "affected_rows": r[4],
             "affected_percent": round(r[5] or 0, 1)}
            for r in findings_rows
        ]

        pending_row = conn.execute(text("""
            SELECT COUNT(*) FROM remediation_scripts rs
            JOIN findings f ON rs.finding_id = f.id
            WHERE f.scan_run_id = :sid AND rs.status = 'pending'
        """), {"sid": scan_run_id}).fetchone()
        pending_count = pending_row[0] if pending_row else 0

    tables_dict = {}
    for f in all_findings:
        t = f["table_name"]
        if t not in tables_dict:
            tables_dict[t] = []
        tables_dict[t].append(f)

    # ── header ──────────────────────────────────
    st.markdown(f"""
    <div style="padding:8px 0 24px">
        <h1 style="font-size:32px;font-weight:700;color:#2C3E50;margin:0 0 8px;letter-spacing:-.02em">
            Data Quality Dashboard
        </h1>
        <p style="font-size:13px;color:#6B7280;margin:0">
            Scan completed {scan_date} &nbsp;·&nbsp; {db_name}
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="margin:12px 0 24px">
        <span class="pill">Duration: {duration}</span>
        <span class="pill">{len(tables_dict)} tables scanned</span>
        <span class="pill"><span class="dot"></span> &nbsp;{scan[5].title()}</span>
        <span class="pill">Scan ID: {short_id}</span>
    </div>
    """, unsafe_allow_html=True)

    # ── score + metrics ──────────────────────────
    score_color = "#DC2626" if score < 50 else "#F59E0B" if score < 75 else "#22C55E"
    grade = "Poor — action required" if score < 50 else "Needs attention" if score < 75 else "Good" if score < 90 else "Excellent"
    grade_bg = "#FEE2E2" if score < 50 else "#FEF3C7" if score < 75 else "#DCFCE7"
    grade_fg = "#991B1B" if score < 50 else "#92400E" if score < 75 else "#166534"

    col_score, col_m1, col_m2, col_m3, col_m4 = st.columns([1.4, 1, 1, 1, 1])

    with col_score:
        st.markdown(f"""
        <div class="card" style="text-align:center;padding:24px 20px">
            <div style="font-size:11px;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:.06em;margin-bottom:14px">Quality Score</div>
            <div style="font-size:52px;font-weight:700;color:{score_color};line-height:1">{score}</div>
            <div style="font-size:12px;color:#9CA3AF;margin:4px 0 14px">/ 100</div>
            <span style="background:{grade_bg};color:{grade_fg};font-size:11px;font-weight:600;padding:3px 12px;border-radius:20px">{grade}</span>
        </div>
        """, unsafe_allow_html=True)

    with col_m1:
        st.markdown(f"""
        <div class="card" style="height:100%">
            <div class="m-lbl">Total findings</div>
            <div class="m-val" style="color:#111827">{total}</div>
            <div class="m-sub">Across {len(tables_dict)} tables</div>
        </div>
        """, unsafe_allow_html=True)

    with col_m2:
        st.markdown(f"""
        <div class="card" style="height:100%">
            <div class="m-lbl">Critical</div>
            <div class="m-val" style="color:#DC2626">{critical_cnt}</div>
            <div class="m-sub">Immediate action</div>
        </div>
        """, unsafe_allow_html=True)

    with col_m3:
        st.markdown(f"""
        <div class="card" style="height:100%">
            <div class="m-lbl">High severity</div>
            <div class="m-val" style="color:#D97706">{sev.get('high', 0)}</div>
            <div class="m-sub">Duplicates &amp; outliers</div>
        </div>
        """, unsafe_allow_html=True)

    with col_m4:
        st.markdown(f"""
        <div class="card" style="height:100%">
            <div class="m-lbl">Pending scripts</div>
            <div class="m-val" style="color:#2563EB">{pending_count}</div>
            <div class="m-sub">Awaiting approval</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── findings by type + by table ──────────────
    col_left, col_right = st.columns(2)

    type_colors = {
        "null": "#D97706", "duplicate": "#2563EB",
        "outlier": "#7C3AED", "orphan_fk": "#DC2626",
        "distribution": "#0891B2",
    }
    max_cnt = max((r[1] for r in type_rows), default=1)

    bars_html = ""
    for r in type_rows:
        pct   = int(r[1] / max_cnt * 100)
        color = type_colors.get(r[0], "#6B7280")
        label = r[0].replace("_", " ").title()
        bars_html += f"""
        <div>
            <div class="bar-label-row"><span>{label}</span><span style="color:#9CA3AF">{r[1]}</span></div>
            <div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
        </div>"""

    with col_left:
        st.markdown(f'<div class="card"><div class="card-title">Findings by type</div>{bars_html}</div>', unsafe_allow_html=True)

    icon_map = {
        "orphan_fk":  ("fi-fk",      '#DC2626', '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'),
        "duplicate":  ("fi-dup",     '#2563EB', '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
        "outlier":    ("fi-outlier", '#7C3AED', '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>'),
        "null":       ("fi-null",    '#D97706', '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'),
    }

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    table_cards = ""
    for tname, tfindings in tables_dict.items():
        types  = {f["issue_type"] for f in tfindings}
        worst  = min([f["severity"] for f in tfindings], key=lambda s: order.get(s, 99))
        itype  = next((t for t in ["orphan_fk", "duplicate", "outlier", "null"] if t in types), "null")
        ic, stroke, path = icon_map[itype]
        badge  = _badge(worst)
        table_cards += f"""
        <div class="finding-row">
            <div class="finding-left">
                <div class="finding-icon {ic}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="2">{path}</svg>
                </div>
                <div>
                    <div class="finding-name">{tname}</div>
                    <div class="finding-count">{len(tfindings)} findings</div>
                </div>
            </div>
            {badge}
        </div>"""

    with col_right:
        st.markdown(f'<div class="card"><div class="card-title">Findings by table</div>{table_cards}</div>', unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── all findings table ───────────────────────
    tbl_rows = ""
    for f in all_findings:
        col   = f["column_name"] or "—"
        badge = _badge(f["severity"])
        tbl_rows += f"""
        <tr>
            <td class="tbl-t">{f['table_name']}</td>
            <td class="tbl-c">{col}</td>
            <td>{f['issue_type']}</td>
            <td>{badge}</td>
            <td>{f['affected_rows']}</td>
            <td>{f['affected_percent']}%</td>
        </tr>"""

    st.markdown(f"""
    <div class="card">
        <div class="card-title">All findings</div>
        <table class="findings-tbl">
            <thead>
                <tr>
                    <th style="width:110px">Table</th>
                    <th style="width:120px">Column</th>
                    <th style="width:110px">Issue</th>
                    <th style="width:90px">Severity</th>
                    <th style="width:100px">Affected rows</th>
                    <th>% affected</th>
                </tr>
            </thead>
            <tbody>{tbl_rows}</tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)