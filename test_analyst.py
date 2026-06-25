# test_analyst.py
# Delete after testing.

from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger
from agents.schema_inspector import inspect_schema
from agents.scanner import run_scan
from agents.analyst import run_analysis

# get connection_id
engine = get_audit_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT TOP 1 id FROM db_connections")).fetchone()
    connection_id = str(row[0])

print("\n── Testing analyst.py ─────────────────────\n")

# 1. create scan run
audit   = AuditLogger()
scan_id = audit.create_scan_run(connection_id, triggered_by="manual")
print(f"✅ scan_run created: {scan_id}\n")

# 2. run schema inspection
print("Running schema inspector...")
schema = inspect_schema(connection_id, scan_id, db_type="sqlserver")
print(f"✅ schema inspected: {len(schema['tables'])} tables\n")

# 3. run scanner
print("Running scanner...")
findings = run_scan(connection_id, scan_id, db_type="sqlserver")
print(f"✅ scanner found: {len(findings)} findings\n")

# 4. run analyst on first 3 findings only (save API calls)
print("Running analyst on first 3 findings...")
sample   = findings[:3]
enriched = run_analysis(sample, connection_id, scan_id)

# 5. print results
print(f"\n── Analyst Results ────────────────────────\n")
for f in enriched:
    print(f"Table:      {f['table']}.{f.get('column', 'N/A')}")
    print(f"Issue:      {f['issue_type']} | Severity: {f.get('severity')}")
    print(f"Impact:     {f.get('business_impact', 'N/A')}/10")
    print(f"Confidence: {f.get('confidence', 'N/A')}")
    print(f"Explanation:\n  {f.get('explanation', 'N/A')}")
    print(f"Root Cause:\n  {f.get('root_cause', 'N/A')}")
    print(f"Action:\n  {f.get('suggested_action', 'N/A')}")
    print("-" * 60)

print(f"\n── Done ────────────────────────────────────\n")