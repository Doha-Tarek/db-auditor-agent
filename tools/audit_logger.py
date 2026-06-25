# tools/audit_logger.py
# Handles all write operations to the audit database.
# Also sets up file logging for developer tracking.
# Every agent imports from here to save results.

import logging
import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from tools.db_connector import get_audit_engine
import config

# ─────────────────────────────────────────────
# 1. FILE LOGGER SETUP
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "logs" / "app.log"

formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger = logging.getLogger("db_auditor")
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


# ─────────────────────────────────────────────
# 2. AUDIT LOGGER CLASS
# ─────────────────────────────────────────────

class AuditLogger:
    """
    Handles all write operations to the audit database.
    Use this class in every agent to save results.
    """

    def __init__(self):
        self.engine = get_audit_engine()


    # ─────────────────────────────────────────
    # SCAN RUNS
    # ─────────────────────────────────────────

    def create_scan_run(
        self,
        connection_id: str,
        triggered_by:  str = "manual"
    ) -> str:
        """
        Creates a new scan run in the database.
        Returns the new scan_run ID as a string.
        """
        scan_id = str(uuid.uuid4())

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO scan_runs (
                    id, connection_id, status, triggered_by, started_at
                ) VALUES (
                    :id, :connection_id, 'running', :triggered_by, :started_at
                )
            """), {
                "id":            scan_id,
                "connection_id": connection_id,
                "triggered_by":  triggered_by,
                "started_at":    datetime.utcnow()
            })

        logger.info(f"scan started | scan_id: {scan_id} | triggered_by: {triggered_by}")
        self._log_event("scan_started", "scan_run", scan_id, f"Scan started | triggered_by: {triggered_by}")
        return scan_id


    def complete_scan_run(
        self,
        scan_id:           str,
        score:             float,
        total_findings:    int = 0,
        critical_findings: int = 0
    ):
        """
        Marks a scan run as completed with final score.
        """
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE scan_runs SET
                    status            = 'completed',
                    completed_at      = :completed_at,
                    overall_score     = :score,
                    total_findings    = :total_findings,
                    critical_findings = :critical_findings
                WHERE id = :id
            """), {
                "id":               scan_id,
                "completed_at":     datetime.utcnow(),
                "score":            score,
                "total_findings":   total_findings,
                "critical_findings": critical_findings
            })

        logger.info(f"scan completed | scan_id: {scan_id} | score: {score} | findings: {total_findings}")
        self._log_event("scan_completed", "scan_run", scan_id, f"Score: {score} | Findings: {total_findings}")


    def fail_scan_run(self, scan_id: str, error_message: str):
        """
        Marks a scan run as failed with error message.
        """
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE scan_runs SET
                    status        = 'failed',
                    completed_at  = :completed_at,
                    error_message = :error_message
                WHERE id = :id
            """), {
                "id":            scan_id,
                "completed_at":  datetime.utcnow(),
                "error_message": error_message
            })

        logger.error(f"scan failed | scan_id: {scan_id} | error: {error_message}")
        self._log_event("scan_failed", "scan_run", scan_id, f"Error: {error_message}")


    # ─────────────────────────────────────────
    # SCHEMA SNAPSHOTS
    # ─────────────────────────────────────────

    def save_schema_snapshot(
        self,
        connection_id: str,
        scan_run_id:   str,
        schema_json:   str,
        table_count:   int
    ) -> str:
        """
        Saves the inspected schema as JSON to the database.
        Returns the snapshot ID.
        """
        snapshot_id = str(uuid.uuid4())

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO schema_snapshots (
                    id, connection_id, scan_run_id,
                    schema_json, table_count, captured_at
                ) VALUES (
                    :id, :connection_id, :scan_run_id,
                    :schema_json, :table_count, :captured_at
                )
            """), {
                "id":            snapshot_id,
                "connection_id": connection_id,
                "scan_run_id":   scan_run_id,
                "schema_json":   schema_json,
                "table_count":   table_count,
                "captured_at":   datetime.utcnow()
            })

        logger.info(f"schema snapshot saved | tables: {table_count} | snapshot_id: {snapshot_id}")
        self._log_event("schema_captured", "schema_snapshot", snapshot_id, f"Tables found: {table_count}")
        return snapshot_id


    # ─────────────────────────────────────────
    # FINDINGS
    # ─────────────────────────────────────────

    def save_finding(
        self,
        scan_run_id:      str,
        table_name:       str,
        issue_type:       str,
        severity:         str,
        affected_rows:    int   = 0,
        total_rows:       int   = 0,
        column_name:      str   = None,
        llm_explanation:  str   = None,
        root_cause:       str   = None,
        business_impact:  int   = 0,
        confidence_score: float = 0.0
    ) -> str:
        """
        Saves a single finding to the database.
        Returns the finding ID.
        """
        finding_id       = str(uuid.uuid4())
        affected_percent = round((affected_rows / total_rows * 100), 2) if total_rows > 0 else 0

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO findings (
                    id, scan_run_id, table_name, column_name,
                    issue_type, severity, affected_rows, total_rows,
                    affected_percent, llm_explanation, root_cause,
                    business_impact, confidence_score, created_at
                ) VALUES (
                    :id, :scan_run_id, :table_name, :column_name,
                    :issue_type, :severity, :affected_rows, :total_rows,
                    :affected_percent, :llm_explanation, :root_cause,
                    :business_impact, :confidence_score, :created_at
                )
            """), {
                "id":                finding_id,
                "scan_run_id":       scan_run_id,
                "table_name":        table_name,
                "column_name":       column_name,
                "issue_type":        issue_type,
                "severity":          severity,
                "affected_rows":     affected_rows,
                "total_rows":        total_rows,
                "affected_percent":  affected_percent,
                "llm_explanation":   llm_explanation,
                "root_cause":        root_cause,
                "business_impact":   business_impact,
                "confidence_score":  confidence_score,
                "created_at":        datetime.utcnow()
            })

        logger.warning(f"finding detected | {severity.upper()} | {issue_type} | table: {table_name} | column: {column_name} | rows affected: {affected_rows}")
        self._log_event("finding_detected", "finding", finding_id, f"{severity.upper()} | {issue_type} in {table_name}")
        return finding_id


    # ─────────────────────────────────────────
    # REMEDIATION SCRIPTS
    # ─────────────────────────────────────────

    def save_remediation_script(
        self,
        finding_id:       str,
        sql_script:       str,
        risk_level:       str,
        explanation:      str   = None,
        rollback:         str   = None,
        confidence_score: float = 0.0
    ) -> str:
        """
        Saves a generated fix SQL script to the database.
        Returns the script ID.
        """
        script_id = str(uuid.uuid4())

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO remediation_scripts (
                    id, finding_id, sql_script,
                    risk_level, explanation, [rollback],
                    confidence_score, status, created_at
                ) VALUES (
                    :id, :finding_id, :sql_script,
                    :risk_level, :explanation, :rollback,
                    :confidence_score, 'pending', :created_at
                )
            """), {
                "id":               script_id,
                "finding_id":       finding_id,
                "sql_script":       sql_script,
                "risk_level":       risk_level,
                "explanation":      explanation,
                "rollback":         rollback,
                "confidence_score": confidence_score,
                "created_at":       datetime.utcnow()
            })

        logger.info(f"remediation script saved | risk: {risk_level.upper()} | script_id: {script_id}")
        self._log_event("script_generated", "remediation_script", script_id, f"Risk: {risk_level} | Finding: {finding_id}")
        return script_id


    def update_script_status(
        self,
        script_id:        str,
        status:           str,
        approved_by:      str = None,
        execution_result: str = None
    ):
        """
        Updates a script status after approval or execution.
        status options: approved | rejected | executed
        """
        now = datetime.utcnow()

        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE remediation_scripts SET
                    status           = :status,
                    approved_by      = :approved_by,
                    approved_at      = CASE WHEN :status IN ('approved','executed') THEN :now ELSE approved_at END,
                    executed_at      = CASE WHEN :status = 'executed' THEN :now ELSE executed_at END,
                    execution_result = :execution_result
                WHERE id = :id
            """), {
                "id":               script_id,
                "status":           status,
                "approved_by":      approved_by,
                "execution_result": execution_result,
                "now":              now
            })

        logger.info(f"script {status} | script_id: {script_id} | by: {approved_by}")
        self._log_event(f"script_{status}", "remediation_script", script_id, f"Status: {status} | By: {approved_by}")


    # ─────────────────────────────────────────
    # AUDIT LOG
    # ─────────────────────────────────────────

    def _log_event(
        self,
        event_type:   str,
        entity_type:  str = None,
        entity_id:    str = None,
        message:      str = None,
        performed_by: str = "system"
    ):
        """
        Internal helper — writes every action to audit_log table.
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO audit_log (
                        id, event_type, entity_type,
                        entity_id, message, performed_by, created_at
                    ) VALUES (
                        :id, :event_type, :entity_type,
                        :entity_id, :message, :performed_by, :created_at
                    )
                """), {
                    "id":           str(uuid.uuid4()),
                    "event_type":   event_type,
                    "entity_type":  entity_type,
                    "entity_id":    entity_id,
                    "message":      message,
                    "performed_by": performed_by,
                    "created_at":   datetime.utcnow()
                })
        except Exception as e:
            logger.error(f"audit_log write failed | {e}")