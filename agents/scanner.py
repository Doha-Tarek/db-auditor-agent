# agents/scanner.py
# Detective agent — finds all data quality problems in target_db.
# READ ONLY — never modifies target_db.
# Results are saved to audit DB via audit_logger.py

from sqlalchemy import text
from tools.db_connector import get_target_engine
from tools.audit_logger import AuditLogger, logger
from tools.schema_reader import (
    list_tables,
    get_nullable_columns,
    get_numeric_columns
)


# ─────────────────────────────────────────────
# 1. MAIN SCAN FUNCTION
# ─────────────────────────────────────────────

def run_scan(
    connection_id: str,
    scan_run_id:   str,
    db_type:       str = "sqlserver"
) -> list[dict]:
    """
    Runs all detection checks on target_db.
    Saves every finding to audit DB.
    Returns list of all findings for Analyst Agent.

    Args:
        connection_id: ID from db_connections table
        scan_run_id:   ID of current scan run
        db_type:       sqlserver | postgresql | mysql

    Returns:
        List of finding dicts
    """
    logger.info(f"scanner started | scan_run_id: {scan_run_id}")

    engine   = get_target_engine(db_type)
    audit    = AuditLogger()
    findings = []

    with engine.connect() as conn:
        tables = list_tables(connection_id)
        logger.info(f"scanner | scanning {len(tables)} tables: {tables}")

        for table in tables:
            logger.info(f"scanner | scanning table: {table}")

            # run all checks per table
            findings += _check_nulls(conn, audit, scan_run_id, connection_id, table)
            findings += _check_duplicates(conn, audit, scan_run_id, table)
            findings += _check_outliers(conn, audit, scan_run_id, connection_id, table)
            findings += _check_orphan_fks(conn, audit, scan_run_id, table)
            findings += _check_distributions(conn, audit, scan_run_id, table)

    logger.info(f"scanner completed | total findings: {len(findings)}")
    return findings


# ─────────────────────────────────────────────
# 2. CHECK — NULL RATES
# ─────────────────────────────────────────────

def _check_nulls(
    conn, audit, scan_run_id, connection_id, table_name
) -> list[dict]:
    """
    Checks null rate for every nullable column in a table.
    Severity based on null percentage.
    """
    findings      = []
    nullable_cols = get_nullable_columns(connection_id)

    # filter to columns in this table only
    cols = [c for c in nullable_cols if c["table_name"] == table_name]

    for col in cols:
        col_name = col["column_name"]

        try:
            result = conn.execute(text(f"""
                SELECT
                    COUNT(*)                                    AS total_rows,
                    SUM(CASE WHEN [{col_name}] IS NULL THEN 1 ELSE 0 END) AS null_rows
                FROM [{table_name}]
            """))
            row        = result.fetchone()
            total_rows = row[0]
            null_rows  = row[1] or 0

            if null_rows == 0:
                continue

            null_pct = round(null_rows / total_rows * 100, 2) if total_rows > 0 else 0

            # determine severity
            if null_pct > 50:
                severity = "critical"
            elif null_pct > 20:
                severity = "high"
            elif null_pct > 5:
                severity = "medium"
            else:
                severity = "low"

            logger.warning(f"scanner | null detected | {table_name}.{col_name} | {null_rows}/{total_rows} ({null_pct}%) | {severity}")

            finding_id = audit.save_finding(
                scan_run_id=scan_run_id,
                table_name=table_name,
                column_name=col_name,
                issue_type="null",
                severity=severity,
                affected_rows=null_rows,
                total_rows=total_rows,
            )

            findings.append({
                "id":           finding_id,
                "table":        table_name,
                "column":       col_name,
                "issue_type":   "null",
                "severity":     severity,
                "affected_rows": null_rows,
                "total_rows":   total_rows,
                "null_pct":     null_pct,
            })

        except Exception as e:
            logger.error(f"scanner | null check failed | {table_name}.{col_name} | {e}")

    return findings


# ─────────────────────────────────────────────
# 3. CHECK — DUPLICATE ROWS
# ─────────────────────────────────────────────

def _check_duplicates(
    conn, audit, scan_run_id, table_name
) -> list[dict]:
    """
    Finds exact duplicate rows in a table.
    A duplicate is a row where ALL columns match another row.
    """
    findings = []

    try:
        # get all column names except id
        col_result = conn.execute(text(f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = :table
            AND COLUMN_NAME != 'id'
            ORDER BY ORDINAL_POSITION
        """), {"table": table_name})

        columns = [row[0] for row in col_result.fetchall()]

        if not columns:
            return findings

        # build GROUP BY on all non-id columns
        col_list = ", ".join([f"[{c}]" for c in columns])

        result = conn.execute(text(f"""
            SELECT COUNT(*) AS total_rows
            FROM [{table_name}]
        """))
        total_rows = result.fetchone()[0]

        dup_result = conn.execute(text(f"""
            SELECT COUNT(*) AS duplicate_count
            FROM (
                SELECT {col_list}, COUNT(*) AS cnt
                FROM [{table_name}]
                GROUP BY {col_list}
                HAVING COUNT(*) > 1
            ) AS dups
        """))

        dup_groups = dup_result.fetchone()[0]

        if dup_groups == 0:
            return findings

        # count total duplicate rows
        dup_rows_result = conn.execute(text(f"""
            SELECT SUM(cnt - 1) AS extra_rows
            FROM (
                SELECT {col_list}, COUNT(*) AS cnt
                FROM [{table_name}]
                GROUP BY {col_list}
                HAVING COUNT(*) > 1
            ) AS dups
        """))

        affected_rows = dup_rows_result.fetchone()[0] or 0

        severity = "high" if affected_rows > 0 else "low"

        logger.warning(f"scanner | duplicates detected | {table_name} | {affected_rows} duplicate rows in {dup_groups} groups | {severity}")

        finding_id = audit.save_finding(
            scan_run_id=scan_run_id,
            table_name=table_name,
            column_name=None,
            issue_type="duplicate",
            severity=severity,
            affected_rows=affected_rows,
            total_rows=total_rows,
        )

        findings.append({
            "id":            finding_id,
            "table":         table_name,
            "column":        None,
            "issue_type":    "duplicate",
            "severity":      severity,
            "affected_rows": affected_rows,
            "total_rows":    total_rows,
            "dup_groups":    dup_groups,
        })

    except Exception as e:
        logger.error(f"scanner | duplicate check failed | {table_name} | {e}")

    return findings


# ─────────────────────────────────────────────
# 4. CHECK — OUTLIERS (IQR METHOD)
# ─────────────────────────────────────────────

def _check_outliers(
    conn, audit, scan_run_id, connection_id, table_name
) -> list[dict]:
    """
    Detects outliers in numeric columns using IQR method.
    IQR = Q3 - Q1
    Outlier = value < Q1 - 1.5*IQR OR value > Q3 + 1.5*IQR
    """
    findings     = []
    numeric_cols = get_numeric_columns(connection_id)

    # filter to this table only — skip FK/ID columns
    skip_cols = {"id", "customer_id", "supplier_id", "manager_id"}
    cols = [
        c for c in numeric_cols
        if c["table_name"] == table_name
        and c["column_name"].lower() not in skip_cols
    ]

    for col in cols:
        col_name = col["column_name"]

        try:
            # get Q1 and Q3 using percentile
            result = conn.execute(text(f"""
                SELECT
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY [{col_name}])
                        OVER () AS q1,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY [{col_name}])
                        OVER () AS q3,
                    COUNT(*)  OVER () AS total_rows
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

            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            # count outliers
            outlier_result = conn.execute(text(f"""
                SELECT COUNT(*) AS outlier_count
                FROM [{table_name}]
                WHERE [{col_name}] IS NOT NULL
                AND (
                    [{col_name}] < :lower
                    OR [{col_name}] > :upper
                )
            """), {"lower": lower_bound, "upper": upper_bound})

            outlier_count = outlier_result.fetchone()[0]

            if outlier_count == 0:
                continue

            severity = "high" if outlier_count > 0 else "low"

            logger.warning(f"scanner | outliers detected | {table_name}.{col_name} | {outlier_count} outliers | bounds: [{lower_bound:.2f}, {upper_bound:.2f}] | {severity}")

            finding_id = audit.save_finding(
                scan_run_id=scan_run_id,
                table_name=table_name,
                column_name=col_name,
                issue_type="outlier",
                severity=severity,
                affected_rows=outlier_count,
                total_rows=total_rows,
            )

            findings.append({
                "id":            finding_id,
                "table":         table_name,
                "column":        col_name,
                "issue_type":    "outlier",
                "severity":      severity,
                "affected_rows": outlier_count,
                "total_rows":    total_rows,
                "lower_bound":   lower_bound,
                "upper_bound":   upper_bound,
            })

        except Exception as e:
            logger.error(f"scanner | outlier check failed | {table_name}.{col_name} | {e}")

    return findings


# ─────────────────────────────────────────────
# 5. CHECK — ORPHAN FOREIGN KEYS
# ─────────────────────────────────────────────

def _check_orphan_fks(
    conn, audit, scan_run_id, table_name
) -> list[dict]:
    """
    Detects orphan foreign keys — rows that reference
    IDs that don't exist in the parent table.
    Uses known relationships since no formal FK constraints exist.
    """
    findings = []

    # define known relationships manually
    # format: {child_table: [(child_col, parent_table, parent_col)]}
    known_fks = {
        "orders":    [("customer_id", "customers", "id")],
        "products":  [("supplier_id", None, None)],   # no suppliers table
        "employees": [("manager_id",  "employees", "id")],
    }

    relationships = known_fks.get(table_name, [])

    for child_col, parent_table, parent_col in relationships:

        # skip if no parent table defined
        if not parent_table:
            continue

        try:
            result = conn.execute(text(f"""
                SELECT COUNT(*) AS total_rows
                FROM [{table_name}]
                WHERE [{child_col}] IS NOT NULL
            """))
            total_rows = result.fetchone()[0]

            orphan_result = conn.execute(text(f"""
                SELECT COUNT(*) AS orphan_count
                FROM [{table_name}] child
                WHERE child.[{child_col}] IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM [{parent_table}] parent
                    WHERE parent.[{parent_col}] = child.[{child_col}]
                )
            """))

            orphan_count = orphan_result.fetchone()[0]

            if orphan_count == 0:
                continue

            severity = "critical"

            logger.warning(f"scanner | orphan FK detected | {table_name}.{child_col} → {parent_table}.{parent_col} | {orphan_count} orphans | {severity}")

            finding_id = audit.save_finding(
                scan_run_id=scan_run_id,
                table_name=table_name,
                column_name=child_col,
                issue_type="orphan_fk",
                severity=severity,
                affected_rows=orphan_count,
                total_rows=total_rows,
            )

            findings.append({
                "id":            finding_id,
                "table":         table_name,
                "column":        child_col,
                "issue_type":    "orphan_fk",
                "severity":      severity,
                "affected_rows": orphan_count,
                "total_rows":    total_rows,
                "parent_table":  parent_table,
                "parent_col":    parent_col,
            })

        except Exception as e:
            logger.error(f"scanner | orphan FK check failed | {table_name}.{child_col} | {e}")

    return findings


# ─────────────────────────────────────────────
# 6. CHECK — SUSPICIOUS DISTRIBUTIONS
# ─────────────────────────────────────────────

def _check_distributions(
    conn, audit, scan_run_id, table_name
) -> list[dict]:
    """
    Finds columns where one value dominates > 80% of rows.
    Could indicate bad default values or data entry issues.
    Checks text/varchar columns only.
    """
    findings = []

    try:
        # get text columns
        col_result = conn.execute(text(f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME   = :table
            AND DATA_TYPE IN ('nvarchar', 'varchar', 'char', 'nchar', 'text')
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

            top_value  = row[0]
            top_count  = row[1]
            total_rows = row[2]

            if total_rows == 0:
                continue

            dominance_pct = round(top_count / total_rows * 100, 2)

            # only flag if one value dominates > 80%
            if dominance_pct <= 80:
                continue

            severity = "medium"

            logger.warning(f"scanner | suspicious distribution | {table_name}.{col_name} | '{top_value}' appears {dominance_pct}% of the time | {severity}")

            finding_id = audit.save_finding(
                scan_run_id=scan_run_id,
                table_name=table_name,
                column_name=col_name,
                issue_type="distribution",
                severity=severity,
                affected_rows=top_count,
                total_rows=total_rows,
            )

            findings.append({
                "id":            finding_id,
                "table":         table_name,
                "column":        col_name,
                "issue_type":    "distribution",
                "severity":      severity,
                "affected_rows": top_count,
                "total_rows":    total_rows,
                "top_value":     top_value,
                "dominance_pct": dominance_pct,
            })

    except Exception as e:
        logger.error(f"scanner | distribution check failed | {table_name} | {e}")

    return findings