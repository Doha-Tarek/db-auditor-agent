# tools/agent_tools.py
# Wraps existing scanner.py functions as CrewAI @tool decorated tools.
# Agents import from here and DECIDE which tools to use themselves.
# No logic is duplicated — we reuse everything from scanner.py directly.
# Tool outputs are kept SHORT to save tokens on Groq free tier.

import json
from crewai.tools import tool
from tools.audit_logger import logger

# import existing functions from scanner.py
from agents.scanner import (
    _check_nulls,
    _check_duplicates,
    _check_outliers,
    _check_orphan_fks,
    _check_distributions,
)

# import existing functions from schema_reader.py
from tools.schema_reader import (
    list_tables,
    get_latest_schema,
    get_nullable_columns,
    get_numeric_columns,
)

# import connectors
from tools.db_connector import get_target_engine, get_audit_engine
from tools.audit_logger import AuditLogger
from sqlalchemy import text


# ─────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────
# Set once before crew runs — all tools read from here.

_state = {
    "connection_id": None,
    "scan_run_id":   None,
    "db_type":       "sqlserver"
}

def set_scan_context(
    connection_id: str,
    scan_run_id:   str,
    db_type:       str = "sqlserver"
):
    """
    Call this before starting a crew run.
    Sets the shared context all tools read from.
    """
    _state["connection_id"] = connection_id
    _state["scan_run_id"]   = scan_run_id
    _state["db_type"]       = db_type
    logger.info(f"agent_tools | context set | connection: {connection_id} | scan: {scan_run_id}")


# ─────────────────────────────────────────────
# TOOL 1 — LIST TABLES
# ─────────────────────────────────────────────

@tool("list_database_tables")
def list_database_tables(placeholder: str = "") -> str:
    """
    Lists all tables in the target database.
    Use this FIRST before any other scan tool.
    Returns a JSON list of table names.

    When to use:
    - At the start of any scan task
    - When you need to know what tables exist
    - Before deciding which tables to inspect
    """
    try:
        tables = list_tables(_state["connection_id"])
        logger.info(f"tool | list_database_tables | found: {tables}")
        return json.dumps({
            "tables": tables,
            "count":  len(tables)
        })
    except Exception as e:
        logger.error(f"tool | list_database_tables | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 2 — GET TABLE SCHEMA
# ─────────────────────────────────────────────

@tool("get_table_schema")
def get_table_schema(table_name: str) -> str:
    """
    Gets schema details for a specific table.
    Use this to understand a table before scanning it.
    Returns columns, types, nullable flags, row count.

    When to use:
    - Before scanning a specific table
    - When you need to know column types
    - To understand table structure and size
    """
    try:
        schema = get_latest_schema(_state["connection_id"])
        table  = schema.get("tables", {}).get(table_name, {})

        if not table:
            return json.dumps({"error": f"Table '{table_name}' not found"})

        # return short summary only — saves tokens
        col_summary = [
            f"{c['name']} ({c['type']}{'  nullable' if c['nullable'] else ''}{'  PK' if c['primary_key'] else ''})"
            for c in table.get("columns", [])
        ]

        return json.dumps({
            "table_name": table_name,
            "row_count":  table.get("row_count", 0),
            "columns":    col_summary,
            "indexes":    table.get("indexes", [])
        })
    except Exception as e:
        logger.error(f"tool | get_table_schema | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 3 — CHECK NULLS
# reuses _check_nulls() from scanner.py
# ─────────────────────────────────────────────

@tool("check_null_rates")
def check_null_rates(table_name: str) -> str:
    """
    Checks null rates for all nullable columns in a table.
    Detects missing values that could indicate data quality issues.
    Saves findings to audit database automatically.

    When to use:
    - When checking a table for missing data
    - When a column might have incomplete records
    - As part of a full table quality scan
    """
    try:
        engine        = get_target_engine(_state["db_type"])
        audit         = AuditLogger()
        nullable_cols = get_nullable_columns(_state["connection_id"])
        cols          = [c for c in nullable_cols if c["table_name"] == table_name]
        findings      = []

        with engine.connect() as conn:
            for col in cols:
                col_name = col["column_name"]
                result   = conn.execute(text(f"""
                    SELECT
                        COUNT(*) AS total_rows,
                        SUM(CASE WHEN [{col_name}] IS NULL THEN 1 ELSE 0 END) AS null_rows
                    FROM [{table_name}]
                """))
                row        = result.fetchone()
                total_rows = row[0]
                null_rows  = row[1] or 0

                if null_rows == 0:
                    continue

                null_pct = round(null_rows / total_rows * 100, 2) if total_rows > 0 else 0
                severity = (
                    "critical" if null_pct > 50 else
                    "high"     if null_pct > 20 else
                    "medium"   if null_pct > 5  else
                    "low"
                )

                audit.save_finding(
                    scan_run_id=_state["scan_run_id"],
                    table_name=table_name,
                    column_name=col_name,
                    issue_type="null",
                    severity=severity,
                    affected_rows=null_rows,
                    total_rows=total_rows,
                )

                # short summary only — saves tokens
                findings.append(f"{col_name}: {null_pct}% nulls ({severity})")
                logger.warning(f"tool | check_null_rates | {table_name}.{col_name} | {null_pct}% | {severity}")

        return json.dumps({
            "table":          table_name,
            "check":          "null_rates",
            "findings_count": len(findings),
            "summary":        findings
        })

    except Exception as e:
        logger.error(f"tool | check_null_rates | {table_name} | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 4 — CHECK DUPLICATES
# reuses _check_duplicates() from scanner.py
# ─────────────────────────────────────────────

@tool("check_duplicate_rows")
def check_duplicate_rows(table_name: str) -> str:
    """
    Finds exact duplicate rows in a table.
    A duplicate is a row where ALL non-id columns match exactly.
    Saves findings to audit database automatically.

    When to use:
    - When checking a table for duplicate records
    - When data may have been imported multiple times
    - As part of a full table quality scan
    """
    try:
        engine = get_target_engine(_state["db_type"])
        audit  = AuditLogger()

        with engine.connect() as conn:
            col_result = conn.execute(text(f"""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = :table AND COLUMN_NAME != 'id'
                ORDER BY ORDINAL_POSITION
            """), {"table": table_name})

            columns  = [row[0] for row in col_result.fetchall()]
            col_list = ", ".join([f"[{c}]" for c in columns])

            total_result = conn.execute(text(f"SELECT COUNT(*) FROM [{table_name}]"))
            total_rows   = total_result.fetchone()[0]

            dup_result = conn.execute(text(f"""
                SELECT SUM(cnt - 1) AS extra_rows, COUNT(*) AS dup_groups
                FROM (
                    SELECT {col_list}, COUNT(*) AS cnt
                    FROM [{table_name}]
                    GROUP BY {col_list}
                    HAVING COUNT(*) > 1
                ) AS dups
            """))

            row        = dup_result.fetchone()
            dup_rows   = row[0] or 0
            dup_groups = row[1] or 0

            if dup_rows == 0:
                return json.dumps({
                    "table":          table_name,
                    "check":          "duplicates",
                    "findings_count": 0,
                    "summary":        "no duplicates found"
                })

            audit.save_finding(
                scan_run_id=_state["scan_run_id"],
                table_name=table_name,
                column_name=None,
                issue_type="duplicate",
                severity="high",
                affected_rows=dup_rows,
                total_rows=total_rows,
            )

            logger.warning(f"tool | check_duplicate_rows | {table_name} | {dup_rows} duplicate rows")

            return json.dumps({
                "table":          table_name,
                "check":          "duplicates",
                "findings_count": 1,
                "summary":        f"{dup_rows} duplicate rows in {dup_groups} groups (high)"
            })

    except Exception as e:
        logger.error(f"tool | check_duplicate_rows | {table_name} | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 5 — CHECK OUTLIERS
# reuses _check_outliers() from scanner.py
# ─────────────────────────────────────────────

@tool("check_outliers")
def check_outliers(table_name: str) -> str:
    """
    Detects statistical outliers in numeric columns using IQR method.
    Outlier = value below Q1-1.5*IQR or above Q3+1.5*IQR.
    Saves findings to audit database automatically.

    When to use:
    - When checking numeric columns for extreme values
    - When a column may contain data entry errors
    - As part of a full table quality scan
    """
    try:
        engine       = get_target_engine(_state["db_type"])
        audit        = AuditLogger()
        numeric_cols = get_numeric_columns(_state["connection_id"])
        skip_cols    = {"id", "customer_id", "supplier_id", "manager_id"}
        cols         = [
            c for c in numeric_cols
            if c["table_name"] == table_name
            and c["column_name"].lower() not in skip_cols
        ]
        findings = []

        with engine.connect() as conn:
            for col in cols:
                col_name = col["column_name"]

                result = conn.execute(text(f"""
                    SELECT
                        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY [{col_name}]) OVER() AS q1,
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY [{col_name}]) OVER() AS q3,
                        COUNT(*) OVER() AS total_rows
                    FROM [{table_name}]
                    WHERE [{col_name}] IS NOT NULL
                """))

                rows = result.fetchall()
                if not rows:
                    continue

                q1         = float(rows[0][0])
                q3         = float(rows[0][1])
                total_rows = rows[0][2]
                iqr        = q3 - q1

                if iqr == 0:
                    continue

                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr

                outlier_result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM [{table_name}]
                    WHERE [{col_name}] IS NOT NULL
                    AND ([{col_name}] < :lower OR [{col_name}] > :upper)
                """), {"lower": lower, "upper": upper})

                outlier_count = outlier_result.fetchone()[0]
                if outlier_count == 0:
                    continue

                audit.save_finding(
                    scan_run_id=_state["scan_run_id"],
                    table_name=table_name,
                    column_name=col_name,
                    issue_type="outlier",
                    severity="high",
                    affected_rows=outlier_count,
                    total_rows=total_rows,
                )

                findings.append(f"{col_name}: {outlier_count} outliers (high)")
                logger.warning(f"tool | check_outliers | {table_name}.{col_name} | {outlier_count} outliers")

        return json.dumps({
            "table":          table_name,
            "check":          "outliers",
            "findings_count": len(findings),
            "summary":        findings
        })

    except Exception as e:
        logger.error(f"tool | check_outliers | {table_name} | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 6 — CHECK ORPHAN FKS
# reuses _check_orphan_fks() from scanner.py
# ─────────────────────────────────────────────

@tool("check_orphan_foreign_keys")
def check_orphan_foreign_keys(table_name: str) -> str:
    """
    Detects orphan foreign keys — rows referencing IDs
    that do not exist in the parent table.
    Saves findings to audit database automatically.

    When to use:
    - When checking referential integrity
    - When a table has columns ending in _id
    - As part of a full table quality scan
    """
    try:
        engine   = get_target_engine(_state["db_type"])
        audit    = AuditLogger()
        findings = []

        known_fks = {
            "orders":    [("customer_id", "customers", "id")],
            "products":  [("supplier_id", None, None)],
            "employees": [("manager_id",  "employees", "id")],
        }

        relationships = known_fks.get(table_name, [])

        with engine.connect() as conn:
            for child_col, parent_table, parent_col in relationships:
                if not parent_table:
                    continue

                total_result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM [{table_name}]
                    WHERE [{child_col}] IS NOT NULL
                """))
                total_rows = total_result.fetchone()[0]

                orphan_result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM [{table_name}] child
                    WHERE child.[{child_col}] IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM [{parent_table}] parent
                        WHERE parent.[{parent_col}] = child.[{child_col}]
                    )
                """))
                orphan_count = orphan_result.fetchone()[0]

                if orphan_count == 0:
                    continue

                audit.save_finding(
                    scan_run_id=_state["scan_run_id"],
                    table_name=table_name,
                    column_name=child_col,
                    issue_type="orphan_fk",
                    severity="critical",
                    affected_rows=orphan_count,
                    total_rows=total_rows,
                )

                findings.append(
                    f"{child_col} → {parent_table}: {orphan_count} orphans (critical)"
                )
                logger.warning(
                    f"tool | check_orphan_foreign_keys | {table_name}.{child_col} | {orphan_count} orphans"
                )

        return json.dumps({
            "table":          table_name,
            "check":          "orphan_fks",
            "findings_count": len(findings),
            "summary":        findings
        })

    except Exception as e:
        logger.error(f"tool | check_orphan_foreign_keys | {table_name} | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 7 — CHECK DISTRIBUTIONS
# reuses _check_distributions() from scanner.py
# ─────────────────────────────────────────────

@tool("check_value_distributions")
def check_value_distributions(table_name: str) -> str:
    """
    Detects suspicious value distributions in text columns.
    Flags columns where one value dominates more than 80% of rows.
    Saves findings to audit database automatically.

    When to use:
    - When checking for bad default values
    - When a text column may have repeated patterns
    - As part of a full table quality scan
    """
    try:
        engine   = get_target_engine(_state["db_type"])
        audit    = AuditLogger()
        findings = []

        with engine.connect() as conn:
            col_result = conn.execute(text(f"""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = :table
                AND DATA_TYPE IN ('nvarchar','varchar','char','nchar','text')
                AND COLUMN_NAME != 'id'
                ORDER BY ORDINAL_POSITION
            """), {"table": table_name})

            columns = [row[0] for row in col_result.fetchall()]

            for col_name in columns:
                result = conn.execute(text(f"""
                    SELECT TOP 1
                        [{col_name}]        AS top_value,
                        COUNT(*)            AS top_count,
                        SUM(COUNT(*)) OVER() AS total_rows
                    FROM [{table_name}]
                    WHERE [{col_name}] IS NOT NULL
                    GROUP BY [{col_name}]
                    ORDER BY COUNT(*) DESC
                """))

                row = result.fetchone()
                if not row:
                    continue

                top_value     = row[0]
                top_count     = row[1]
                total_rows    = row[2]
                dominance_pct = round(top_count / total_rows * 100, 2) if total_rows > 0 else 0

                if dominance_pct <= 80:
                    continue

                audit.save_finding(
                    scan_run_id=_state["scan_run_id"],
                    table_name=table_name,
                    column_name=col_name,
                    issue_type="distribution",
                    severity="medium",
                    affected_rows=top_count,
                    total_rows=total_rows,
                )

                findings.append(
                    f"{col_name}: '{top_value}' dominates {dominance_pct}% (medium)"
                )
                logger.warning(
                    f"tool | check_value_distributions | {table_name}.{col_name} | {dominance_pct}%"
                )

        return json.dumps({
            "table":          table_name,
            "check":          "distributions",
            "findings_count": len(findings),
            "summary":        findings
        })

    except Exception as e:
        logger.error(f"tool | check_value_distributions | {table_name} | error: {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# TOOL 8 — GET SCAN SUMMARY
# ─────────────────────────────────────────────

@tool("get_scan_summary")
def get_scan_summary(placeholder: str = "") -> str:
    """
    Returns summary of all findings saved so far in this scan.
    Use this at the END of scanning to get a complete picture.
    Call with empty string: get_scan_summary("")

    When to use:
    - After scanning all tables
    - When preparing the final scan report
    - To verify all findings were saved correctly
    """
    try:
        engine = get_audit_engine()

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT issue_type, severity, COUNT(*) AS count
                FROM findings
                WHERE scan_run_id = :scan_id
                GROUP BY issue_type, severity
                ORDER BY severity, issue_type
            """), {"scan_id": _state["scan_run_id"]})

            rows  = result.fetchall()
            total = 0
            lines = []

            for row in rows:
                total += row[2]
                lines.append(f"{row[0]} ({row[1]}): {row[2]}")

        logger.info(f"tool | get_scan_summary | total: {total}")
        return json.dumps({
            "total_findings": total,
            "summary":        lines
        })

    except Exception as e:
        logger.error(f"tool | get_scan_summary | error: {e}")
        return json.dumps({"error": str(e)})

# ─────────────────────────────────────────────
# ALL TOOLS LIST
# ─────────────────────────────────────────────
# Import this in crew.py to assign tools to agents

ALL_SCAN_TOOLS = [
    list_database_tables,       # 0
    get_table_schema,           # 1
    check_null_rates,           # 2
    check_duplicate_rows,       # 3
    check_outliers,             # 4
    check_orphan_foreign_keys,  # 5
    check_value_distributions,  # 6
    get_scan_summary,           # 7
]