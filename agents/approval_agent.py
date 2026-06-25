# agents/approval_agent.py
# Human-in-the-loop approval workflow.
# Presents pending scripts, validates them, executes on approval.
# NEVER executes without explicit human confirmation.

from tools.sql_runner import dry_run, execute_script, reject_script
from tools.audit_logger import AuditLogger, logger
from agents.remediator import get_pending_scripts


# ─────────────────────────────────────────────
# 1. SHOW PENDING SCRIPTS
# ─────────────────────────────────────────────

def show_pending_scripts(scan_run_id: str) -> list[dict]:
    """
    Returns all pending scripts for a scan run.
    Called by UI to display what needs review.

    Args:
        scan_run_id: ID of the completed scan run

    Returns:
        List of pending script dicts ordered by risk
    """
    scripts = get_pending_scripts(scan_run_id)
    logger.info(f"approval_agent | pending scripts: {len(scripts)}")
    return scripts


# ─────────────────────────────────────────────
# 2. APPROVE AND EXECUTE
# ─────────────────────────────────────────────

def approve_script(
    script_id:   str,
    sql_script:  str,
    approved_by: str = "user",
    db_type:     str = "sqlserver"
) -> dict:
    """
    Approves and executes a remediation script.
    Runs dry-run validation first before executing.

    Args:
        script_id:   ID from remediation_scripts table
        sql_script:  SQL script to execute
        approved_by: username approving the script
        db_type:     sqlserver | postgresql | mysql

    Returns:
        Dict with success bool, message, rows_affected
    """
    logger.info(f"approval_agent | approving | script_id: {script_id} | by: {approved_by}")

    # ── Step 1: dry run validation ─────────────
    validation = dry_run(sql_script, db_type)

    if not validation["success"]:
        logger.error(f"approval_agent | dry run failed | {validation['message']}")
        return {
            "success": False,
            "message": f"Validation failed — script not executed: {validation['message']}",
            "rows_affected": 0
        }

    logger.info("approval_agent | dry run passed — executing")

    # ── Step 2: execute ────────────────────────
    result = execute_script(
        script_id=script_id,
        sql_script=sql_script,
        approved_by=approved_by,
        db_type=db_type
    )

    if result["success"]:
        logger.info(f"approval_agent | executed | rows affected: {result['rows_affected']}")
    else:
        logger.error(f"approval_agent | execution failed | {result['message']}")

    return result


# ─────────────────────────────────────────────
# 3. REJECT SCRIPT
# ─────────────────────────────────────────────

def reject_script_by_user(
    script_id:   str,
    rejected_by: str = "user",
    reason:      str = None
) -> dict:
    """
    Rejects a script — marks it as rejected in audit DB.
    Script will never be executed.

    Args:
        script_id:   ID from remediation_scripts table
        rejected_by: username rejecting
        reason:      optional reason for rejection

    Returns:
        Dict with success bool and message
    """
    logger.info(f"approval_agent | rejecting | script_id: {script_id} | by: {rejected_by}")

    result = reject_script(
        script_id=script_id,
        rejected_by=rejected_by,
        reason=reason
    )

    return result


# ─────────────────────────────────────────────
# 4. APPROVE ALL SAFE SCRIPTS
# ─────────────────────────────────────────────

def approve_all_safe(
    scan_run_id: str,
    approved_by: str = "user",
    db_type:     str = "sqlserver"
) -> dict:
    """
    Auto-approves and executes all SAFE risk scripts.
    Moderate and destructive scripts still need manual approval.
    Useful for bulk processing low-risk fixes.

    Args:
        scan_run_id: ID of the scan run
        approved_by: username approving
        db_type:     target DB type

    Returns:
        Dict with counts of executed and failed scripts
    """
    logger.info(f"approval_agent | auto-approving safe scripts | scan: {scan_run_id}")

    scripts  = get_pending_scripts(scan_run_id)
    safe     = [s for s in scripts if s["risk_level"] == "safe"]

    executed = 0
    failed   = 0

    for script in safe:
        result = approve_script(
            script_id=script["script_id"],
            sql_script=script["sql_script"],
            approved_by=approved_by,
            db_type=db_type
        )
        if result["success"]:
            executed += 1
        else:
            failed += 1

    logger.info(f"approval_agent | auto-approve complete | executed: {executed} | failed: {failed}")

    return {
        "total_safe": len(safe),
        "executed":   executed,
        "failed":     failed,
        "message":    f"Auto-approved {executed}/{len(safe)} safe scripts"
    }


# ─────────────────────────────────────────────
# 5. GET APPROVAL SUMMARY
# ─────────────────────────────────────────────

def get_approval_summary(scan_run_id: str) -> dict:
    """
    Returns a summary of script statuses for a scan.
    Used by UI dashboard to show approval progress.

    Args:
        scan_run_id: ID of the scan run

    Returns:
        Dict with counts by status and risk level
    """
    from sqlalchemy import text
    from tools.db_connector import get_audit_engine

    engine = get_audit_engine()

    with engine.connect() as conn:

        # count by status
        status_rows = conn.execute(text("""
            SELECT rs.status, COUNT(*) AS cnt
            FROM remediation_scripts rs
            JOIN findings f ON rs.finding_id = f.id
            WHERE f.scan_run_id = :scan_id
            GROUP BY rs.status
        """), {"scan_id": scan_run_id}).fetchall()

        status_counts = {r[0]: r[1] for r in status_rows}

        # count by risk level
        risk_rows = conn.execute(text("""
            SELECT rs.risk_level, COUNT(*) AS cnt
            FROM remediation_scripts rs
            JOIN findings f ON rs.finding_id = f.id
            WHERE f.scan_run_id = :scan_id
            GROUP BY rs.risk_level
        """), {"scan_id": scan_run_id}).fetchall()

        risk_counts = {r[0]: r[1] for r in risk_rows}

    return {
        "pending":     status_counts.get("pending",  0),
        "approved":    status_counts.get("approved", 0),
        "executed":    status_counts.get("executed", 0),
        "rejected":    status_counts.get("rejected", 0),
        "failed":      status_counts.get("failed",   0),
        "safe":        risk_counts.get("safe",        0),
        "moderate":    risk_counts.get("moderate",    0),
        "destructive": risk_counts.get("destructive", 0),
    }