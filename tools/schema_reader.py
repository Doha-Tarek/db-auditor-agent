# tools/schema_reader.py
# Reads saved schema snapshots from the audit DB.
# Every agent that needs schema info imports from here.
# Never re-connect to target_db just to read schema — use this instead.

import json
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.audit_logger import logger


# ─────────────────────────────────────────────
# 1. GET FULL SCHEMA
# ─────────────────────────────────────────────

def get_latest_schema(connection_id: str) -> dict:
    """
    Returns the most recent schema snapshot for a connection.
    This is the full schema dict saved by schema_inspector.py.

    Args:
        connection_id: ID from db_connections table

    Returns:
        Full schema dict with tables, columns, FKs, indexes, row counts.
        Empty dict if no snapshot found.
    """
    engine = get_audit_engine()

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT TOP 1 schema_json
            FROM schema_snapshots
            WHERE connection_id = :cid
            ORDER BY captured_at DESC
        """), {"cid": connection_id})

        row = result.fetchone()

        if not row:
            logger.warning(f"schema_reader | no snapshot found for connection_id: {connection_id}")
            return {}

        schema = json.loads(row[0])
        logger.debug(f"schema_reader | loaded schema | tables: {list(schema.get('tables', {}).keys())}")
        return schema


# ─────────────────────────────────────────────
# 2. GET SINGLE TABLE SUMMARY
# ─────────────────────────────────────────────

def get_table_summary(connection_id: str, table_name: str) -> dict:
    """
    Returns schema info for a single table only.
    Lighter than loading the full schema when you only need one table.

    Args:
        connection_id: ID from db_connections table
        table_name:    name of the table to get info for

    Returns:
        Dict with columns, foreign_keys, indexes, row_count.
        Empty dict if table not found.
    """
    schema = get_latest_schema(connection_id)
    table  = schema.get("tables", {}).get(table_name, {})

    if not table:
        logger.warning(f"schema_reader | table '{table_name}' not found in snapshot")

    return table


# ─────────────────────────────────────────────
# 3. LIST ALL TABLES
# ─────────────────────────────────────────────

def list_tables(connection_id: str) -> list[str]:
    """
    Returns just the table names for a connection.
    Used by Scanner Agent to know what tables to scan.

    Args:
        connection_id: ID from db_connections table

    Returns:
        List of table name strings.
        Empty list if no snapshot found.
    """
    schema = get_latest_schema(connection_id)
    tables = list(schema.get("tables", {}).keys())
    logger.debug(f"schema_reader | list_tables | found: {tables}")
    return tables


# ─────────────────────────────────────────────
# 4. GET FOREIGN KEYS
# ─────────────────────────────────────────────

def get_foreign_keys(connection_id: str) -> list[dict]:
    """
    Returns all FK relationships across all tables.
    Used by Scanner Agent for orphan FK detection.
    Used by Remediator Agent before generating fix SQL.

    Args:
        connection_id: ID from db_connections table

    Returns:
        List of dicts with from_table, from_column, to_table, to_column.
        Empty list if no FKs found.

    Example return:
        [
            {
                "from_table":  "orders",
                "from_column": "customer_id",
                "to_table":    "customers",
                "to_column":   "id"
            }
        ]
    """
    schema = get_latest_schema(connection_id)
    fks    = []

    for table_name, info in schema.get("tables", {}).items():
        for fk in info.get("foreign_keys", []):
            fks.append({
                "from_table":  table_name,
                "from_column": fk["from_column"],
                "to_table":    fk["to_table"],
                "to_column":   fk["to_column"]
            })

    logger.debug(f"schema_reader | get_foreign_keys | found: {len(fks)} FK relationships")
    return fks


# ─────────────────────────────────────────────
# 5. GET NULLABLE COLUMNS
# ─────────────────────────────────────────────

def get_nullable_columns(connection_id: str) -> list[dict]:
    """
    Returns all nullable columns across all tables.
    Used by Scanner Agent to know which columns to check for nulls.

    Returns:
        List of dicts with table_name and column_name.

    Example return:
        [
            {"table_name": "customers", "column_name": "email"},
            {"table_name": "orders",    "column_name": "amount"}
        ]
    """
    schema          = get_latest_schema(connection_id)
    nullable_cols   = []

    for table_name, info in schema.get("tables", {}).items():
        for col in info.get("columns", []):
            if col.get("nullable") and not col.get("primary_key"):
                nullable_cols.append({
                    "table_name":  table_name,
                    "column_name": col["name"],
                    "type":        col["type"]
                })

    logger.debug(f"schema_reader | get_nullable_columns | found: {len(nullable_cols)} nullable columns")
    return nullable_cols


# ─────────────────────────────────────────────
# 6. GET NUMERIC COLUMNS
# ─────────────────────────────────────────────

def get_numeric_columns(connection_id: str) -> list[dict]:
    """
    Returns all numeric columns across all tables.
    Used by Scanner Agent for outlier detection.

    Returns:
        List of dicts with table_name and column_name.
    """
    schema       = get_latest_schema(connection_id)
    numeric_cols = []

    # numeric types across all 3 DB engines
    numeric_types = {
        "int", "bigint", "smallint", "tinyint",
        "decimal", "numeric", "float", "real",
        "money", "smallmoney", "double", "double precision"
    }

    for table_name, info in schema.get("tables", {}).items():
        for col in info.get("columns", []):
            if col.get("type", "").lower() in numeric_types and not col.get("primary_key"):
                numeric_cols.append({
                    "table_name":  table_name,
                    "column_name": col["name"],
                    "type":        col["type"]
                })

    logger.debug(f"schema_reader | get_numeric_columns | found: {len(numeric_cols)} numeric columns")
    return numeric_cols