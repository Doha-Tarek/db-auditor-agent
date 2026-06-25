# agents/reporter.py
# Generates HTML and PDF reports from scan results.
# Reads findings from audit DB, renders Jinja2 templates,
# exports HTML and PDF to reports/output/ folder.

import json
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import logger
from reports.pdf_generator import generate_pdf, save_html, build_filename


# ─────────────────────────────────────────────
# JINJA2 ENVIRONMENT
# ─────────────────────────────────────────────

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "reports" / "templates"
jinja_env     = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


# ─────────────────────────────────────────────
# MAIN REPORT FUNCTION
# ─────────────────────────────────────────────

def generate_report(
    scan_run_id:   str,
    connection_id: str,
    llm_analysis:  str = None,
    generate_pdf_file: bool = True
) -> dict:
    """
    Generates full HTML + PDF report for a completed scan.
    Reads all data from audit DB and renders Jinja2 templates.

    Args:
        scan_run_id:       ID of the completed scan run
        connection_id:     ID from db_connections table
        llm_analysis:      analyst agent output string (optional)
        generate_pdf_file: whether to also generate PDF

    Returns:
        Dict with paths to generated HTML and PDF files
    """
    logger.info(f"reporter | generating report | scan_run_id: {scan_run_id}")

    # load all data from audit DB
    data = _load_report_data(scan_run_id, connection_id, llm_analysis)

    # render full report
    html_content  = _render_full_report(data)
    filename      = build_filename(scan_run_id, "full")
    html_path     = save_html(html_content, filename)

    result = {"html": html_path, "pdf": None}

    # render executive summary
    exec_content  = _render_executive_summary(data)
    exec_filename = build_filename(scan_run_id, "executive")
    exec_html_path = save_html(exec_content, exec_filename)
    result["executive_html"] = exec_html_path

    # generate PDFs
    if generate_pdf_file:
        try:
            pdf_path       = generate_pdf(html_content, filename)
            exec_pdf_path  = generate_pdf(exec_content, exec_filename)
            result["pdf"]           = pdf_path
            result["executive_pdf"] = exec_pdf_path
        except Exception as e:
            logger.warning(f"reporter | PDF generation failed | {e} | HTML still saved")

    logger.info(f"reporter | report generated | html: {html_path}")
    return result


# ─────────────────────────────────────────────
# LOAD ALL REPORT DATA FROM AUDIT DB
# ─────────────────────────────────────────────

def _load_report_data(
    scan_run_id:   str,
    connection_id: str,
    llm_analysis:  str = None
) -> dict:
    """
    Loads all data needed for the report from audit DB.
    Returns a single dict passed to both Jinja2 templates.
    """
    engine = get_audit_engine()

    with engine.connect() as conn:

        # ── scan run info ──────────────────────
        scan_row = conn.execute(text("""
            SELECT
                started_at, completed_at,
                overall_score, total_findings,
                critical_findings, status
            FROM scan_runs
            WHERE id = :scan_id
        """), {"scan_id": scan_run_id}).fetchone()

        started_at   = scan_row[0]
        completed_at = scan_row[1]
        score        = int(scan_row[2] or 0)
        total        = scan_row[3] or 0
        critical     = scan_row[4] or 0

        duration = "N/A"
        if started_at and completed_at:
            secs     = int((completed_at - started_at).total_seconds())
            duration = f"{secs}s" if secs < 60 else f"{secs // 60}m {secs % 60}s"

        # ── db connection name ─────────────────
        conn_row = conn.execute(text("""
            SELECT name, db_type FROM db_connections WHERE id = :cid
        """), {"cid": connection_id}).fetchone()
        db_name = conn_row[0] if conn_row else "Unknown Database"

        # ── all findings ───────────────────────
        findings_rows = conn.execute(text("""
            SELECT
                table_name, column_name, issue_type,
                severity, affected_rows, total_rows,
                affected_percent, llm_explanation,
                root_cause, business_impact
            FROM findings
            WHERE scan_run_id = :scan_id
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high'     THEN 2
                    WHEN 'medium'   THEN 3
                    WHEN 'low'      THEN 4
                    ELSE 5
                END,
                table_name
        """), {"scan_id": scan_run_id}).fetchall()

        all_findings = [
            {
                "table_name":       r[0],
                "column_name":      r[1],
                "issue_type":       r[2],
                "severity":         r[3],
                "affected_rows":    r[4],
                "total_rows":       r[5],
                "affected_percent": round(r[6] or 0, 1),
                "llm_explanation":  r[7],
                "root_cause":       r[8],
                "business_impact":  r[9],
            }
            for r in findings_rows
        ]

        # ── findings by type ───────────────────
        type_rows = conn.execute(text("""
            SELECT issue_type, COUNT(*) AS cnt
            FROM findings
            WHERE scan_run_id = :scan_id
            GROUP BY issue_type
            ORDER BY cnt DESC
        """), {"scan_id": scan_run_id}).fetchall()

        findings_by_type = [
            {
                "issue_type": r[0],
                "count":      r[1],
                "severity":   _get_type_severity(r[0]),
                "pct":        round(r[1] / total * 100) if total > 0 else 0
            }
            for r in type_rows
        ]

        # ── severity counts ────────────────────
        sev_rows = conn.execute(text("""
            SELECT severity, COUNT(*) AS cnt
            FROM findings
            WHERE scan_run_id = :scan_id
            GROUP BY severity
        """), {"scan_id": scan_run_id}).fetchall()

        sev_counts = {r[0]: r[1] for r in sev_rows}

        # ── remediation scripts ────────────────
        script_rows = conn.execute(text("""
            SELECT
                rs.sql_script, rs.risk_level,
                rs.explanation, rs.status,
                f.table_name, f.issue_type
            FROM remediation_scripts rs
            JOIN findings f ON rs.finding_id = f.id
            WHERE f.scan_run_id = :scan_id
            ORDER BY
                CASE rs.risk_level
                    WHEN 'safe'        THEN 1
                    WHEN 'moderate'    THEN 2
                    WHEN 'destructive' THEN 3
                END
        """), {"scan_id": scan_run_id}).fetchall()

        scripts = [
            {
                "sql_script":  r[0],
                "risk_level":  r[1],
                "explanation": r[2],
                "status":      r[3],
                "table_name":  r[4],
                "issue_type":  r[5],
            }
            for r in script_rows
        ]

        # ── per table breakdown ────────────────
        tables_rows = conn.execute(text("""
            SELECT DISTINCT table_name FROM findings
            WHERE scan_run_id = :scan_id
            ORDER BY table_name
        """), {"scan_id": scan_run_id}).fetchall()

        tables = []
        for trow in tables_rows:
            tname = trow[0]
            tfindings = [f for f in all_findings if f["table_name"] == tname]
            tables.append({
                "name":          tname,
                "row_count":     tfindings[0]["total_rows"] if tfindings else 0,
                "finding_count": len(tfindings),
                "findings":      tfindings
            })

        # ── recommended actions ────────────────
        recommended_actions = _build_recommendations(all_findings)

        # ── score grade ────────────────────────
        if score >= 90:
            grade = "Excellent"
        elif score >= 75:
            grade = "Good"
        elif score >= 50:
            grade = "Needs Attention"
        else:
            grade = "Poor — Action Required"

        # ── LLM analysis items ─────────────────
        llm_items = [
            f for f in all_findings
            if f.get("llm_explanation")
        ]

    return {
        "scan_id":           scan_run_id,
        "db_name":           db_name,
        "scan_date":         started_at.strftime("%Y-%m-%d %H:%M") if started_at else "N/A",
        "duration":          duration,
        "table_count":       len(tables),
        "overall_score":     score,
        "score_grade":       grade,
        "total_findings":    total,
        "critical_count":    sev_counts.get("critical", 0),
        "high_count":        sev_counts.get("high",     0),
        "medium_count":      sev_counts.get("medium",   0),
        "low_count":         sev_counts.get("low",      0),
        "findings_by_type":  findings_by_type,
        "all_findings":      all_findings,
        "critical_findings": [f for f in all_findings if f["severity"] == "critical"],
        "llm_analysis":      llm_items,
        "remediation_scripts": scripts,
        "tables":            tables,
        "recommended_actions": recommended_actions,
    }


# ─────────────────────────────────────────────
# RENDER TEMPLATES
# ─────────────────────────────────────────────

def _render_full_report(data: dict) -> str:
    template = jinja_env.get_template("full_report.html")
    return template.render(**data)


def _render_executive_summary(data: dict) -> str:
    template = jinja_env.get_template("executive_summary.html")
    return template.render(**data)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _get_type_severity(issue_type: str) -> str:
    """Maps issue type to default severity color for display."""
    mapping = {
        "orphan_fk":    "critical",
        "duplicate":    "high",
        "outlier":      "high",
        "null":         "medium",
        "distribution": "medium",
    }
    return mapping.get(issue_type, "low")


def _build_recommendations(findings: list) -> list:
    """Builds a short list of recommended actions from findings."""
    recs  = []
    types = set(f["issue_type"] for f in findings)

    if "orphan_fk" in types:
        recs.append("Fix orphan foreign keys — review referential integrity and add missing parent records")
    if "duplicate" in types:
        recs.append("Remove duplicate rows — implement unique constraints to prevent recurrence")
    if "outlier" in types:
        recs.append("Investigate outlier values — verify whether they are data entry errors or valid edge cases")
    if "null" in types:
        recs.append("Address null values — backfill missing data and add NOT NULL constraints where appropriate")
    if "distribution" in types:
        recs.append("Review suspicious distributions — check for bad default values or data entry patterns")

    recs.append("Run remediation scripts after reviewing and approving each one individually")
    recs.append("Schedule automated scans to monitor data quality trends over time")

    return recs