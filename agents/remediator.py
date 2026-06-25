# agents/remediator.py
# Generates SQL fix scripts for each finding.
# Uses Grok LLM with remediator_prompt.txt.
# Scripts are saved to audit DB — never executed without approval.
# Risk levels: safe | moderate | destructive

import json
from pathlib import Path
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger, logger
from tools.grok_client import ask_grok_json
from tools.schema_reader import get_latest_schema


# ─────────────────────────────────────────────
# 1. LOAD PROMPT
# ─────────────────────────────────────────────

def _load_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / "remediator_prompt.txt"
    if not path.exists():
        raise FileNotFoundError(f"[remediator] prompt not found: {path}")
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────
# 2. MAIN REMEDIATION FUNCTION
# ─────────────────────────────────────────────

def run_remediation(
    findings:      list[dict],
    connection_id: str,
    scan_run_id:   str
) -> list[dict]:
    """
    Generates SQL fix scripts for all findings.
    Saves each script to audit DB with risk classification.
    Never executes — waits for human approval.

    Args:
        findings:      list of finding dicts from scanner
        connection_id: ID from db_connections table
        scan_run_id:   ID of current scan run

    Returns:
        List of remediation script dicts
    """
    logger.info(f"remediator | starting | findings: {len(findings)}")

    system_prompt = _load_prompt()
    schema        = get_latest_schema(connection_id)
    audit         = AuditLogger()
    scripts       = []

    # group findings by table+issue to avoid duplicate scripts
    seen = set()

    for finding in findings:
        key = f"{finding['table']}_{finding['issue_type']}_{finding.get('column', '')}"

        if key in seen:
            continue
        seen.add(key)

        logger.info(
            f"remediator | generating script | "
            f"{finding['issue_type']} | "
            f"{finding['table']}.{finding.get('column', 'N/A')}"
        )

        try:
            user_message = _build_user_message(finding, schema)
            result       = ask_grok_json(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=600
            )

            result = _validate_result(result)

            # save to audit DB
            script_id = audit.save_remediation_script(
                finding_id=finding["id"],
                sql_script=result["sql_script"],
                risk_level=result["risk_level"],
                explanation=result.get("explanation", ""),
                rollback=result.get("rollback", ""),
                confidence_score=result.get("confidence", 0.0)
            )

            scripts.append({
                "script_id":   script_id,
                "finding_id":  finding["id"],
                "table":       finding["table"],
                "column":      finding.get("column"),
                "issue_type":  finding["issue_type"],
                "severity":    finding["severity"],
                "sql_script":  result["sql_script"],
                "risk_level":  result["risk_level"],
                "explanation": result.get("explanation", ""),
                "rollback":    result.get("rollback", ""),
                "confidence":  result.get("confidence", 0.0),
                "status":      "pending"
            })

            logger.info(
                f"remediator | script saved | "
                f"risk: {result['risk_level']} | "
                f"script_id: {script_id}"
            )

        except Exception as e:
            logger.error(
                f"remediator | failed | "
                f"{finding['table']}.{finding.get('column')} | {e}"
            )

    logger.info(f"remediator | completed | scripts generated: {len(scripts)}")
    return scripts


# ─────────────────────────────────────────────
# 3. BUILD USER MESSAGE
# ─────────────────────────────────────────────

def _build_user_message(finding: dict, schema: dict) -> str:
    """
    Builds the user message sent to LLM for each finding.
    Includes finding details + relevant schema context.
    """
    table_name   = finding["table"]
    col_name     = finding.get("column")
    table_schema = schema.get("tables", {}).get(table_name, {})
    columns      = table_schema.get("columns", [])
    fks          = table_schema.get("foreign_keys", [])

    col_descriptions = "\n".join([
        f"  - {c['name']}: {c['type']}"
        f"{'  NOT NULL' if not c.get('nullable') else ''}"
        f"{'  PK' if c.get('primary_key') else ''}"
        for c in columns
    ])

    fk_text      = json.dumps(fks) if fks else "none"
    extra_context = _get_issue_context(finding)

    return f"""
FINDING TO FIX:
- Table:         {table_name}
- Column:        {col_name or 'entire table'}
- Issue Type:    {finding['issue_type']}
- Severity:      {finding['severity']}
- Affected Rows: {finding['affected_rows']} out of {finding['total_rows']}

TABLE SCHEMA:
- Columns:
{col_descriptions}
- Foreign Keys: {fk_text}

ADDITIONAL CONTEXT:
{extra_context}

DATABASE: SQL Server (T-SQL syntax only)

Generate a safe SQL fix script for this finding.
Return ONLY valid JSON — no markdown, no preamble.
""".strip()


# ─────────────────────────────────────────────
# 4. ISSUE-SPECIFIC CONTEXT
# ─────────────────────────────────────────────

def _get_issue_context(finding: dict) -> str:
    """Adds issue-type specific context for the LLM."""
    issue_type = finding["issue_type"]
    table      = finding["table"]
    column     = finding.get("column", "")

    contexts = {
        "null": (
            f"Column [{column}] has {finding['affected_rows']} NULL values. "
            f"Generate an UPDATE script that sets a safe default value. "
            f"Do NOT use DELETE — nulls should be filled, not removed."
        ),
        "duplicate": (
            f"Table [{table}] has {finding['affected_rows']} exact duplicate rows. "
            f"Generate a DELETE script that removes duplicates keeping one copy. "
            f"Use a CTE with ROW_NUMBER() to identify and remove duplicates safely."
        ),
        "outlier": (
            f"Column [{column}] has {finding['affected_rows']} statistical outliers. "
            f"Generate a SELECT script to identify the outlier rows for review. "
            f"Do NOT delete or update — outliers need human review first. "
            f"Risk level must be 'safe'."
        ),
        "orphan_fk": (
            f"Column [{column}] has {finding['affected_rows']} rows referencing "
            f"IDs that don't exist in the parent table. "
            f"Generate a script to SET these to NULL (safer than DELETE). "
            f"Include the parent table name in the WHERE clause."
        ),
        "distribution": (
            f"Column [{column}] has suspicious value distribution. "
            f"Generate a SELECT script to show the distribution for review. "
            f"Risk level must be 'safe'."
        ),
    }

    return contexts.get(issue_type, "Generate a safe fix for this data quality issue.")


# ─────────────────────────────────────────────
# 5. VALIDATE RESULT
# ─────────────────────────────────────────────

def _validate_result(result: dict) -> dict:
    """
    Validates and sanitizes the LLM response.
    Falls back to safe defaults if values are missing.
    """
    valid_risks = {"safe", "moderate", "destructive"}

    if not result.get("sql_script"):
        result["sql_script"] = "-- Script generation failed. Please write manually."

    # ── fix escaped newlines from LLM JSON output ──
    result["sql_script"] = result["sql_script"].replace("\\n", "\n").replace("\\t", "\t")

    if result.get("risk_level") not in valid_risks:
        result["risk_level"] = "moderate"

    if not result.get("explanation"):
        result["explanation"] = "Automated fix script."

    if not result.get("rollback"):
        result["rollback"] = "Restore from backup before executing."

    try:
        result["confidence"] = round(
            max(0.0, min(1.0, float(result.get("confidence", 0.7)))), 2
        )
    except (ValueError, TypeError):
        result["confidence"] = 0.7

    return result


# ─────────────────────────────────────────────
# 6. GET PENDING SCRIPTS
# ─────────────────────────────────────────────

def get_pending_scripts(scan_run_id: str) -> list[dict]:
    """
    Returns all pending remediation scripts for a scan.
    Used by the Approval Agent and UI to show what needs review.
    """
    engine = get_audit_engine()

    with engine.connect() as conn:
        rows = conn.execute(text("""
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
            AND rs.status = 'pending'
            ORDER BY
                CASE rs.risk_level
                    WHEN 'destructive' THEN 1
                    WHEN 'moderate'    THEN 2
                    WHEN 'safe'        THEN 3
                END,
                f.affected_rows DESC
        """), {"scan_id": scan_run_id}).fetchall()

        return [
            {
                "script_id":     str(r[0]),
                "sql_script":    r[1],
                "risk_level":    r[2],
                "explanation":   r[3],
                "rollback":      r[4],
                "status":        r[5],
                "confidence":    float(r[6] or 0),
                "created_at":    str(r[7]),
                "table_name":    r[8],
                "column_name":   r[9],
                "issue_type":    r[10],
                "severity":      r[11],
                "affected_rows": r[12],
            }
            for r in rows
        ]