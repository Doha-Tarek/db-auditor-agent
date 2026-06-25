import sys
import io
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import os
from dotenv import load_dotenv

# ── load env first ─────────────────────────
load_dotenv()
os.environ["GROQ_API_KEY"]   = os.getenv("GROK_API_KEY", "")
os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")

from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger, logger
from agents.schema_inspector import inspect_schema
from agents.scanner import run_scan
from agents.reporter import generate_report
from agents.remediator import run_remediation, get_pending_scripts
from agents.approval_agent import get_approval_summary
from crew import run_analyst_crew


def main():
    logger.info("-" * 60)
    logger.info("db auditor agent | starting")
    logger.info("-" * 60)

    # ── get connection_id ──────────────────────
    engine = get_audit_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT TOP 1 id FROM db_connections WHERE is_active = 1")
        ).fetchone()

        if not row:
            logger.error("no active db connection found in audit DB")
            print("❌ No active connection found")
            return

        connection_id = str(row[0])
        logger.info(f"main | connection_id: {connection_id}")

    # ── create scan run ────────────────────────
    audit   = AuditLogger()
    scan_id = audit.create_scan_run(
        connection_id=connection_id,
        triggered_by="manual"
    )
    logger.info(f"main | scan_run_id: {scan_id}")

    try:
        # ── STEP 1: Schema Inspector ───────────────
        print("\n" + "-" * 60)
        print("🔍 STEP 1 — Inspecting schema...")
        print("-" * 60)

        schema = inspect_schema(
            connection_id=connection_id,
            scan_run_id=scan_id,
            db_type="sqlserver"
        )
        print(f"✅ Schema inspected — {len(schema['tables'])} tables found")

        # ── STEP 2: Scanner ────────────────────────
        print("\n" + "-" * 60)
        print("🔎 STEP 2 — Scanning for data quality issues...")
        print("-" * 60)

        findings = run_scan(
            connection_id=connection_id,
            scan_run_id=scan_id,
            db_type="sqlserver"
        )
        print(f"✅ Scan complete — {len(findings)} findings detected")

        # print quick summary
        by_type = {}
        for f in findings:
            by_type[f["issue_type"]] = by_type.get(f["issue_type"], 0) + 1
        for issue_type, count in by_type.items():
            print(f"   → {issue_type:<20} {count} findings")

        # ── update scan run with score ─────────────
        severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
        penalty          = sum(severity_weights.get(f.get("severity", "low"), 1) for f in findings)
        score            = max(0, round(100 - penalty, 1))
        critical_count   = sum(1 for f in findings if f.get("severity") == "critical")

        audit.complete_scan_run(
            scan_id=scan_id,
            score=score,
            total_findings=len(findings),
            critical_findings=critical_count
        )
        print(f"   → Quality score: {score}/100")

        # ── STEP 3: Analyst Agent (LLM) ────────────
        print("\n" + "-" * 60)
        print("🧠 STEP 3 — Analyst Agent reasoning about findings...")
        print("-" * 60)

        result = run_analyst_crew(
            connection_id=connection_id,
            scan_run_id=scan_id,
            findings=findings,
        )

        print("\n" + "-" * 60)
        print("✅ ANALYSIS COMPLETE")
        print("-" * 60)
        print(result)

        # ── STEP 4: Generate Reports ────────────────
        print("\n" + "-" * 60)
        print("📄 STEP 4 — Generating reports...")
        print("-" * 60)

        report_paths = generate_report(
            scan_run_id=scan_id,
            connection_id=connection_id,
            llm_analysis=str(result),
            generate_pdf_file=True
        )

        print(f"✅ Full HTML     → {report_paths['html']}")
        print(f"✅ Executive     → {report_paths['executive_html']}")
        if report_paths.get("pdf"):
            print(f"✅ Full PDF      → {report_paths['pdf']}")
        if report_paths.get("executive_pdf"):
            print(f"✅ Executive PDF → {report_paths['executive_pdf']}")

        # ── STEP 5: Remediator ─────────────────────
        print("\n" + "-" * 60)
        print("🔧 STEP 5 — Generating remediation scripts...")
        print("-" * 60)

        scripts = run_remediation(
            findings=findings,
            connection_id=connection_id,
            scan_run_id=scan_id
        )

        print(f"✅ Scripts generated: {len(scripts)}")
        for s in scripts:
            print(
                f"   → [{s['risk_level'].upper():<11}] "
                f"{s['issue_type']:<15} | "
                f"{s['table']}.{s.get('column') or 'table'}"
            )

        # ── approval summary ───────────────────────
        summary = get_approval_summary(scan_id)
        print(f"\n   Pending approval:  {summary['pending']}")
        print(f"   Safe scripts:      {summary['safe']}")
        print(f"   Moderate scripts:  {summary['moderate']}")
        print(f"   Destructive:       {summary['destructive']}")

        # ── FINAL OUTPUT ───────────────────────────
        print("\n" + "-" * 60)
        print("✅ FULL PIPELINE COMPLETE")
        print("-" * 60)
        print(f"   Scan ID:      {scan_id}")
        print(f"   Findings:     {len(findings)}")
        print(f"   Score:        {score}/100")
        print(f"   Scripts:      {len(scripts)} generated | {summary['pending']} pending approval")
        print(f"   Reports:      reports/output/")
        print(f"\n   Next step: streamlit run ui/app.py")
        print("-" * 60 + "\n")

    except Exception as e:
        audit.fail_scan_run(scan_id, str(e))
        logger.error(f"main | scan failed | {e}")
        print(f"\nScan failed: {e}")


if __name__ == "__main__":
    main()