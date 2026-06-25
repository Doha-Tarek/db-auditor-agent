# agents/analyst.py
# Takes raw scanner findings and enriches them with LLM reasoning.
# Reads analyst_prompt.txt and sends each finding to the LLM.
# Updates findings in audit DB with explanation, root cause, severity.

import json
from pathlib import Path
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger, logger
from tools.grok_client import ask_grok_json
from tools.schema_reader import get_latest_schema


# ─────────────────────────────────────────────
# 1. LOAD PROMPT FROM FILE
# ─────────────────────────────────────────────

def _load_prompt() -> str:
    """
    Reads analyst_prompt.txt from prompts/ folder.
    Called once per analysis run.
    """
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "analyst_prompt.txt"

    if not prompt_path.exists():
        raise FileNotFoundError(f"[analyst] prompt file not found: {prompt_path}")

    return prompt_path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────
# 2. MAIN ANALYSIS FUNCTION
# ─────────────────────────────────────────────

def run_analysis(
    findings:      list[dict],
    connection_id: str,
    scan_run_id:   str
) -> list[dict]:
    """
    Analyzes all findings from the Scanner Agent.
    Sends each finding to LLM for explanation and scoring.
    Updates findings in audit DB with LLM results.

    Args:
        findings:      list of finding dicts from scanner.py
        connection_id: ID from db_connections table
        scan_run_id:   ID of current scan run

    Returns:
        List of enriched finding dicts with LLM analysis added
    """
    logger.info(f"analyst started | findings to analyze: {len(findings)}")

    system_prompt = _load_prompt()
    schema        = get_latest_schema(connection_id)
    enriched      = []

    for i, finding in enumerate(findings, 1):
        logger.info(f"analyst | analyzing finding {i}/{len(findings)} | {finding['issue_type']} | {finding['table']}.{finding.get('column', 'N/A')}")

        try:
            # build context message for LLM
            user_message = _build_user_message(finding, schema)

            # send to LLM
            result = ask_grok_json(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=400
            )

            # validate LLM response
            result = _validate_result(result, finding)

            # update finding in audit DB
            _update_finding(finding["id"], result)

            # merge LLM results into finding dict
            enriched_finding = {**finding, **result}
            enriched.append(enriched_finding)

            logger.info(
                f"analyst | finding enriched | "
                f"severity: {result['severity']} | "
                f"impact: {result['business_impact']}/10 | "
                f"confidence: {result['confidence']}"
            )

        except Exception as e:
            logger.error(f"analyst | failed to analyze finding | {finding.get('id')} | {e}")
            enriched.append(finding)  # keep raw finding if LLM fails

    # update scan run with final counts
    _update_scan_summary(scan_run_id, enriched)

    logger.info(f"analyst completed | enriched: {len(enriched)} findings")
    return enriched


# ─────────────────────────────────────────────
# 3. BUILD USER MESSAGE
# ─────────────────────────────────────────────

def _build_user_message(finding: dict, schema: dict) -> str:
    """
    Builds the user message sent to the LLM for each finding.
    Includes finding details + relevant schema context.
    """
    table_name = finding["table"]
    col_name   = finding.get("column")

    # get schema info for this table
    table_schema = schema.get("tables", {}).get(table_name, {})
    columns      = table_schema.get("columns", [])
    row_count    = table_schema.get("row_count", 0)
    fks          = table_schema.get("foreign_keys", [])

    # build column descriptions
    col_descriptions = []
    for col in columns:
        nullable = "nullable" if col.get("nullable") else "not nullable"
        pk       = " (PRIMARY KEY)" if col.get("primary_key") else ""
        col_descriptions.append(f"  - {col['name']}: {col['type']}, {nullable}{pk}")

    col_text = "\n".join(col_descriptions) if col_descriptions else "  - No column info available"
    fk_text  = json.dumps(fks) if fks else "No foreign keys defined"

    # build the full message
    message = f"""
FINDING TO ANALYZE:
- Table:         {table_name}
- Column:        {col_name or 'entire table'}
- Issue Type:    {finding['issue_type']}
- Severity:      {finding['severity']}
- Affected Rows: {finding['affected_rows']} out of {finding['total_rows']} total rows
- Affected %:    {round(finding['affected_rows'] / finding['total_rows'] * 100, 1) if finding['total_rows'] > 0 else 0}%

TABLE SCHEMA CONTEXT:
- Table Name:  {table_name}
- Total Rows:  {row_count}
- Columns:
{col_text}
- Foreign Keys: {fk_text}

ADDITIONAL CONTEXT:
{_get_additional_context(finding)}

Analyze this finding and return your assessment as JSON.
"""
    return message.strip()


# ─────────────────────────────────────────────
# 4. ADDITIONAL CONTEXT PER ISSUE TYPE
# ─────────────────────────────────────────────

def _get_additional_context(finding: dict) -> str:
    """
    Adds issue-type specific context to help the LLM
    give more accurate analysis.
    """
    issue_type = finding["issue_type"]

    contexts = {
        "null": (
            f"This column has {finding['affected_rows']} NULL values. "
            f"Consider whether NULLs are expected or represent missing data."
        ),
        "duplicate": (
            f"Found {finding['affected_rows']} duplicate rows. "
            f"Duplicates may have been caused by failed deduplication, "
            f"multiple data imports, or missing unique constraints."
        ),
        "outlier": (
            f"Statistical outliers detected using IQR method. "
            f"Lower bound: {finding.get('lower_bound', 'N/A'):.2f}, "
            f"Upper bound: {finding.get('upper_bound', 'N/A'):.2f}. "
            f"Outliers may be data entry errors or legitimate edge cases."
            if finding.get("lower_bound") is not None
            else "Statistical outliers detected using IQR method."
        ),
        "orphan_fk": (
            f"Found {finding['affected_rows']} rows referencing IDs that "
            f"don't exist in the parent table. This breaks referential integrity "
            f"and may cause errors in joins and reports."
        ),
        "distribution": (
            f"One value dominates {finding.get('dominance_pct', 'N/A')}% of rows. "
            f"Top value: '{finding.get('top_value', 'N/A')}'. "
            f"This may indicate a bad default value or data entry pattern."
            if finding.get("dominance_pct") is not None
            else "Suspicious value distribution detected."
        ),
    }

    return contexts.get(issue_type, "No additional context available.")


# ─────────────────────────────────────────────
# 5. VALIDATE LLM RESULT
# ─────────────────────────────────────────────

def _validate_result(result: dict, finding: dict) -> dict:
    """
    Validates and sanitizes the LLM response.
    Falls back to safe defaults if values are missing or invalid.
    """
    valid_severities = {"critical", "high", "medium", "low", "info"}

    # explanation
    if not result.get("explanation"):
        result["explanation"] = f"Automated finding: {finding['issue_type']} detected in {finding['table']}"

    # root cause
    if not result.get("root_cause"):
        result["root_cause"] = "Root cause analysis unavailable."

    # business impact — must be int 1-10
    try:
        impact = int(result.get("business_impact", 5))
        result["business_impact"] = max(1, min(10, impact))
    except (ValueError, TypeError):
        result["business_impact"] = 5

    # severity — must be valid value
    if result.get("severity") not in valid_severities:
        result["severity"] = finding["severity"]

    # confidence — must be float 0-1
    try:
        confidence = float(result.get("confidence", 0.7))
        result["confidence"] = round(max(0.0, min(1.0, confidence)), 2)
    except (ValueError, TypeError):
        result["confidence"] = 0.7

    # suggested action
    if not result.get("suggested_action"):
        result["suggested_action"] = "Review and address this finding manually."

    return result


# ─────────────────────────────────────────────
# 6. UPDATE FINDING IN AUDIT DB
# ─────────────────────────────────────────────

def _update_finding(finding_id: str, result: dict):
    """
    Updates the finding in audit DB with LLM analysis results.
    Called after each successful LLM analysis.
    """
    engine = get_audit_engine()

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE findings SET
                llm_explanation  = :explanation,
                root_cause       = :root_cause,
                business_impact  = :business_impact,
                severity         = :severity,
                confidence_score = :confidence
            WHERE id = :id
        """), {
            "id":              finding_id,
            "explanation":     result["explanation"],
            "root_cause":      result["root_cause"],
            "business_impact": result["business_impact"],
            "severity":        result["severity"],
            "confidence":      result["confidence"],
        })


# ─────────────────────────────────────────────
# 7. UPDATE SCAN SUMMARY
# ─────────────────────────────────────────────

def _update_scan_summary(scan_run_id: str, findings: list[dict]):
    """
    Updates scan_runs table with final finding counts and quality score.
    Quality score = 100 - penalty for each finding weighted by severity.
    """
    severity_weights = {
        "critical": 10,
        "high":      5,
        "medium":    2,
        "low":       1,
        "info":      0
    }

    total_findings    = len(findings)
    critical_findings = sum(1 for f in findings if f.get("severity") == "critical")

    # calculate quality score
    penalty = sum(severity_weights.get(f.get("severity", "low"), 1) for f in findings)
    score   = max(0, round(100 - penalty, 1))

    audit = AuditLogger()
    audit.complete_scan_run(
        scan_id=scan_run_id,
        score=score,
        total_findings=total_findings,
        critical_findings=critical_findings
    )

    logger.info(f"analyst | quality score: {score}/100 | critical: {critical_findings} | total: {total_findings}")