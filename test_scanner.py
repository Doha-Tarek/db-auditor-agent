# test_scanner.py
# Delete after testing.

from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger
from agents.scanner import run_scan

# get connection_id
engine = get_audit_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT TOP 1 id FROM db_connections")).fetchone()
    connection_id = str(row[0])

# create scan run
audit   = AuditLogger()
scan_id = audit.create_scan_run(connection_id, triggered_by="manual")

print(f"\n── Testing scanner.py ─────────────────────\n")
print(f"scan_id: {scan_id}\n")

# run scan
findings = run_scan(
    connection_id=connection_id,
    scan_run_id=scan_id,
    db_type="sqlserver"
)

# print summary
print(f"\n── Findings Summary ───────────────────────")
print(f"Total findings: {len(findings)}\n")

by_type = {}
for f in findings:
    t = f["issue_type"]
    by_type[t] = by_type.get(t, 0) + 1

for issue_type, count in by_type.items():
    print(f"  {issue_type:<20} {count} findings")

print(f"\n── Findings Detail ────────────────────────")
for f in findings:
    col = f.get("column") or "entire table"
    print(f"  [{f['severity'].upper():<8}] {f['issue_type']:<15} | {f['table']}.{col} | {f['affected_rows']} rows affected")

print(f"\n── Done ────────────────────────────────────\n")