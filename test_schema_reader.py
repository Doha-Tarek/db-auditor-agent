# test_schema_reader.py
# Delete after testing.

from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.schema_reader import (
    get_latest_schema,
    get_table_summary,
    list_tables,
    get_foreign_keys,
    get_nullable_columns,
    get_numeric_columns
)

# get connection_id
engine = get_audit_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT TOP 1 id FROM db_connections")).fetchone()
    connection_id = str(row[0])

print("\n── Testing schema_reader.py ───────────────\n")

# 1. list tables
print("1. list_tables():")
tables = list_tables(connection_id)
print(f"   ✅ {tables}\n")

# 2. table summary
print("2. get_table_summary() for customers:")
summary = get_table_summary(connection_id, "customers")
print(f"   ✅ columns: {[c['name'] for c in summary['columns']]}")
print(f"   ✅ row_count: {summary['row_count']}\n")

# 3. foreign keys
print("3. get_foreign_keys():")
fks = get_foreign_keys(connection_id)
print(f"   ✅ {len(fks)} FK relationships found")
print(f"   {fks}\n")

# 4. nullable columns
print("4. get_nullable_columns():")
nullables = get_nullable_columns(connection_id)
for col in nullables:
    print(f"   → {col['table_name']}.{col['column_name']} ({col['type']})")
print()

# 5. numeric columns
print("5. get_numeric_columns():")
numerics = get_numeric_columns(connection_id)
for col in numerics:
    print(f"   → {col['table_name']}.{col['column_name']} ({col['type']})")

print("\n── Done ────────────────────────────────────\n")