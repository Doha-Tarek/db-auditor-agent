# test_approval.py
# Delete after testing.

from sqlalchemy import text
from tools.db_connector import get_audit_engine
from agents.approval_agent import (
    show_pending_scripts,
    get_approval_summary,
    approve_all_safe
)

# get latest scan_run_id
engine = get_audit_engine()
with engine.connect() as conn:
    row = conn.execute(text("""
        SELECT TOP 1 id FROM scan_runs
        WHERE status = 'completed'
        ORDER BY completed_at DESC
    """)).fetchone()
    scan_run_id = str(row[0])

print(f"\n── Testing approval_agent.py ──────────────\n")
print(f"scan_run_id: {scan_run_id}\n")

# 1. show pending
print("1. Pending scripts:")
scripts = show_pending_scripts(scan_run_id)
print(f"   ✅ {len(scripts)} scripts pending\n")

for s in scripts[:3]:
    print(f"   [{s['risk_level'].upper():<11}] {s['issue_type']:<15} | {s['table_name']}")

# 2. summary
print("\n2. Approval summary:")
summary = get_approval_summary(scan_run_id)
print(f"   ✅ pending:     {summary['pending']}")
print(f"   ✅ safe:        {summary['safe']}")
print(f"   ✅ moderate:    {summary['moderate']}")
print(f"   ✅ destructive: {summary['destructive']}")

# 3. auto-approve safe scripts
print("\n3. Auto-approving safe scripts:")
result = approve_all_safe(scan_run_id, approved_by="test_user")
print(f"   ✅ {result['message']}")

print(f"\n── Done ────────────────────────────────────\n")