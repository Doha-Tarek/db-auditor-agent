# agents/schema_inspector.py
# First agent that runs in every scan.
# Connects to target_db, reads full schema, saves snapshot to audit DB.
# READ ONLY — never modifies target_db.

import json
from sqlalchemy import text
from crewai import Agent, Task, Crew, Process
from tools.db_connector import get_target_engine
from tools.audit_logger import AuditLogger, logger
from tools.grok_client import ask_grok


# ─────────────────────────────────────────────
# 1. CORE SCHEMA INSPECTION FUNCTION
# ─────────────────────────────────────────────

def inspect_schema(connection_id: str, scan_run_id: str, db_type: str = "sqlserver") -> dict:
    """
    Connects to target DB and reads full schema.
    Saves snapshot to audit DB.
    Returns schema dict for next agents to use.

    Args:
        connection_id: ID from db_connections table
        scan_run_id:   ID of current scan run
        db_type:       sqlserver | postgresql | mysql

    Returns:
        Full schema as a dict
    """
    logger.info(f"schema inspector started | connection_id: {connection_id}")

    engine = get_target_engine(db_type)
    audit  = AuditLogger()
    schema = {"tables": {}, "db_type": db_type}

    with engine.connect() as conn:

        # ── Step 1: get all table names ───────
        tables = _get_tables(conn, db_type)
        logger.info(f"schema inspector | found {len(tables)} tables: {tables}")

        # ── Step 2: inspect each table ────────
        for table_name in tables:
            logger.info(f"schema inspector | inspecting table: {table_name}")

            schema["tables"][table_name] = {
                "columns":      _get_columns(conn, table_name, db_type),
                "foreign_keys": _get_foreign_keys(conn, table_name, db_type),
                "indexes":      _get_indexes(conn, table_name, db_type),
                "row_count":    _get_row_count(conn, table_name),
            }

    # ── Step 3: ask LLM for schema summary ───
    schema["llm_summary"] = _get_llm_summary(schema)

    # ── Step 4: save snapshot to audit DB ────
    snapshot_id = audit.save_schema_snapshot(
        connection_id=connection_id,
        scan_run_id=scan_run_id,
        schema_json=json.dumps(schema),
        table_count=len(schema["tables"])
    )

    logger.info(f"schema inspector completed | tables: {len(schema['tables'])} | snapshot_id: {snapshot_id}")
    return schema


# ─────────────────────────────────────────────
# 2. HELPER — GET ALL TABLES
# ─────────────────────────────────────────────

def _get_tables(conn, db_type: str) -> list[str]:
    """Returns list of all user table names in the database."""

    queries = {
        "sqlserver":  "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME",
        "postgresql": "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'public' ORDER BY TABLE_NAME",
        "mysql":      "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME",
    }

    result = conn.execute(text(queries[db_type]))
    return [row[0] for row in result.fetchall()]


# ─────────────────────────────────────────────
# 3. HELPER — GET COLUMNS
# ─────────────────────────────────────────────

def _get_columns(conn, table_name: str, db_type: str) -> list[dict]:
    """Returns all columns with type, nullable, and primary key info."""

    queries = {
        "sqlserver": """
            SELECT
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.CHARACTER_MAXIMUM_LENGTH,
                CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_PRIMARY_KEY
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                    ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                AND tc.TABLE_NAME = :table
            ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
            WHERE c.TABLE_NAME = :table
            ORDER BY c.ORDINAL_POSITION
        """,
        "postgresql": """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.character_maximum_length,
                CASE WHEN pk.column_name IS NOT NULL THEN 1 ELSE 0 END AS is_primary_key
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                    ON tc.constraint_name = ku.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_name = :table
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_name = :table
            ORDER BY c.ordinal_position
        """,
        "mysql": """
            SELECT
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.CHARACTER_MAXIMUM_LENGTH,
                CASE WHEN c.COLUMN_KEY = 'PRI' THEN 1 ELSE 0 END AS IS_PRIMARY_KEY
            FROM INFORMATION_SCHEMA.COLUMNS c
            WHERE c.TABLE_NAME = :table
            AND c.TABLE_SCHEMA = DATABASE()
            ORDER BY c.ORDINAL_POSITION
        """
    }

    result = conn.execute(text(queries[db_type]), {"table": table_name})
    columns = []
    for row in result.fetchall():
        columns.append({
            "name":        row[0],
            "type":        row[1],
            "nullable":    row[2] == "YES",
            "max_length":  row[3],
            "primary_key": bool(row[4])
        })
    return columns


# ─────────────────────────────────────────────
# 4. HELPER — GET FOREIGN KEYS
# ─────────────────────────────────────────────

def _get_foreign_keys(conn, table_name: str, db_type: str) -> list[dict]:
    """Returns all foreign key relationships for a table."""

    queries = {
        "sqlserver": """
            SELECT
                fk_col.COLUMN_NAME          AS from_column,
                pk_tab.TABLE_NAME           AS to_table,
                pk_col.COLUMN_NAME          AS to_column
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE fk_col
                ON rc.CONSTRAINT_NAME = fk_col.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE pk_col
                ON rc.UNIQUE_CONSTRAINT_NAME = pk_col.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk_tab
                ON rc.UNIQUE_CONSTRAINT_NAME = pk_tab.CONSTRAINT_NAME
            WHERE fk_col.TABLE_NAME = :table
        """,
        "postgresql": """
            SELECT
                kcu.column_name             AS from_column,
                ccu.table_name              AS to_table,
                ccu.column_name             AS to_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name = :table
        """,
        "mysql": """
            SELECT
                COLUMN_NAME                 AS from_column,
                REFERENCED_TABLE_NAME       AS to_table,
                REFERENCED_COLUMN_NAME      AS to_column
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_NAME = :table
            AND TABLE_SCHEMA = DATABASE()
            AND REFERENCED_TABLE_NAME IS NOT NULL
        """
    }

    result = conn.execute(text(queries[db_type]), {"table": table_name})
    fks = []
    for row in result.fetchall():
        fks.append({
            "from_column": row[0],
            "to_table":    row[1],
            "to_column":   row[2]
        })
    return fks


# ─────────────────────────────────────────────
# 5. HELPER — GET INDEXES
# ─────────────────────────────────────────────

def _get_indexes(conn, table_name: str, db_type: str) -> list[str]:
    """Returns list of index names for a table."""

    queries = {
        "sqlserver": """
            SELECT i.name
            FROM sys.indexes i
            JOIN sys.tables t ON i.object_id = t.object_id
            WHERE t.name = :table
            AND i.name IS NOT NULL
        """,
        "postgresql": """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = :table
        """,
        "mysql": """
            SELECT DISTINCT INDEX_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_NAME = :table
            AND TABLE_SCHEMA = DATABASE()
        """
    }

    result = conn.execute(text(queries[db_type]), {"table": table_name})
    return [row[0] for row in result.fetchall()]


# ─────────────────────────────────────────────
# 6. HELPER — GET ROW COUNT
# ─────────────────────────────────────────────

def _get_row_count(conn, table_name: str) -> int:
    """Returns the total number of rows in a table."""
    result = conn.execute(text(f"SELECT COUNT(*) FROM [{table_name}]"))
    return result.fetchone()[0]


# ─────────────────────────────────────────────
# 7. HELPER — LLM SCHEMA SUMMARY
# ─────────────────────────────────────────────

def _get_llm_summary(schema: dict) -> str:
    """
    Asks the LLM to summarize the schema in plain English.
    Helps the Chat Agent answer high-level questions about the DB.
    """
    table_info = []
    for table, info in schema["tables"].items():
        col_names = [c["name"] for c in info["columns"]]
        table_info.append(f"- {table}: {len(col_names)} columns ({', '.join(col_names[:5])}{'...' if len(col_names) > 5 else ''}), {info['row_count']} rows")

    tables_text = "\n".join(table_info)

    try:
        summary = ask_grok(
            system_prompt="You are a senior database architect. Summarize database schemas clearly and concisely.",
            user_message=f"Summarize this database schema in 2-3 sentences:\n{tables_text}",
            max_tokens=150
        )
        return summary
    except Exception as e:
        logger.warning(f"schema LLM summary failed | {e}")
        return "Schema summary unavailable."