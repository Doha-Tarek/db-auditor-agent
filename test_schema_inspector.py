# test_schema_inspector.py
# Delete after testing.

from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import AuditLogger
from agents.schema_inspector import inspect_schema
import json

print("\n── Testing schema_inspector.py ────────────\n")

# 1. get connection_id
engine = get_audit_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT TOP 1 id FROM db_connections")).fetchone()
    connection_id = str(row[0])
    print(f"✅ connection_id: {connection_id}\n")

# 2. create a scan run
audit   = AuditLogger()
scan_id = audit.create_scan_run(connection_id, triggered_by="manual")
print(f"✅ scan_run created: {scan_id}\n")

# 3. run schema inspection
schema = inspect_schema(
    connection_id=connection_id,
    scan_run_id=scan_id,
    db_type="sqlserver"
)

# 4. print results
print(f"✅ tables found: {list(schema['tables'].keys())}\n")
for table, info in schema["tables"].items():
    print(f"   {table}:")
    print(f"     columns   : {[c['name'] for c in info['columns']]}")
    print(f"     row_count : {info['row_count']}")
    print(f"     fk count  : {len(info['foreign_keys'])}")
    print(f"     indexes   : {info['indexes']}")
    print()

print(f"✅ LLM summary:\n   {schema['llm_summary']}\n")
print("── Done ────────────────────────────────────\n")