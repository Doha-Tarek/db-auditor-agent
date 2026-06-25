# test_agent_tools.py
# Delete after testing.

import json
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger
from tools.agent_tools import (
    set_scan_context,
    list_database_tables,
    get_table_schema,
    check_null_rates,
    check_duplicate_rows,
    check_outliers,
    check_orphan_foreign_keys,
    get_scan_summary
)

# setup
engine = get_audit_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT TOP 1 id FROM db_connections")).fetchone()
    connection_id = str(row[0])

audit   = AuditLogger()
scan_id = audit.create_scan_run(connection_id, triggered_by="manual")

# set shared context
set_scan_context(connection_id, scan_id, "sqlserver")

print("\n── Testing agent_tools.py ─────────────────\n")

# 1. list tables
print("1. list_database_tables:")
result = json.loads(list_database_tables.run(""))
print(f"   ✅ {result['tables']}\n")

# 2. get schema
print("2. get_table_schema for orders:")
result = json.loads(get_table_schema.run("orders"))
print(f"   ✅ columns: {[c['name'] for c in result['columns']]}")
print(f"   ✅ row_count: {result['row_count']}\n")

# 3. check nulls
print("3. check_null_rates for customers:")
result = json.loads(check_null_rates.run("customers"))
print(f"   ✅ findings: {result['findings_count']}")
for f in result['findings']:
    print(f"   → {f['column']}: {f['null_pct']}% nulls | {f['severity']}")
print()

# 4. check duplicates
print("4. check_duplicate_rows for customers:")
result = json.loads(check_duplicate_rows.run("customers"))
print(f"   ✅ findings: {result['findings_count']}")
if result['findings_count'] > 0:
    print(f"   → {result['findings'][0]['affected_rows']} duplicate rows")
print()

# 5. check outliers
print("5. check_outliers for employees:")
result = json.loads(check_outliers.run("employees"))
print(f"   ✅ findings: {result['findings_count']}")
for f in result['findings']:
    print(f"   → {f['column']}: {f['affected_rows']} outliers")
print()

# 6. check orphan FKs
print("6. check_orphan_foreign_keys for orders:")
result = json.loads(check_orphan_foreign_keys.run("orders"))
print(f"   ✅ findings: {result['findings_count']}")
for f in result['findings']:
    print(f"   → {f['column']} → {f['parent_table']}: {f['affected_rows']} orphans")
print()

# 7. scan summary
print("7. get_scan_summary:")
result = json.loads(get_scan_summary.run(""))
print(f"   ✅ total findings: {result['total_findings']}")
for issue_type, details in result['by_type'].items():
    for d in details:
        print(f"   → {issue_type:<15} {d['severity']:<10} count: {d['count']}")

print(f"\n── Done ────────────────────────────────────\n")