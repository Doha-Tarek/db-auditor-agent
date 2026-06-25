# config.py
# Single source of truth for all configuration.
# Every other file imports from here — never hardcode secrets anywhere else.

import os
from pathlib import Path
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# 1. LOAD .env FILE
# ─────────────────────────────────────────────
# Looks for .env in the project root (same folder as this file).
# If .env doesn't exist yet, it won't crash — just reads from
# system environment variables instead.

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ─────────────────────────────────────────────
# 2. GROK AI (xAI)
# ─────────────────────────────────────────────
# Your Grok API key from: https://console.x.ai
# All agents that call Grok use GROK_API_KEY and GROK_MODEL.

GROK_API_KEY    = os.getenv("GROK_API_KEY")
GROK_MODEL      = os.getenv("GROK_MODEL", "grok-3")
GROK_MAX_TOKENS = int(os.getenv("GROK_MAX_TOKENS", "1000"))


# ─────────────────────────────────────────────
# 3. TARGET DATABASES (databases you want to audit)
# ─────────────────────────────────────────────
# These are the databases your agents will SCAN.
# Format examples:
#   PostgreSQL  → postgresql+psycopg2://user:password@host:5432/dbname
#   MySQL       → mysql+pymysql://user:password@host:3306/dbname
#   SQL Server  → mssql+pyodbc://user:password@host/dbname?driver=ODBC+Driver+17+for+SQL+Server

POSTGRES_URL   = os.getenv("POSTGRES_URL")
MYSQL_URL      = os.getenv("MYSQL_URL")
SQLSERVER_URL  = os.getenv("SQLSERVER_URL")

# All active target connections in one list.
# Scanner and Schema Inspector iterate over this.
# None values are automatically filtered out.
TARGET_CONNECTIONS = {k: v for k, v in {
    "postgresql": POSTGRES_URL,
    "mysql":      MYSQL_URL,
    "sqlserver":  SQLSERVER_URL,
}.items() if v is not None}


# ─────────────────────────────────────────────
# 4. AUDIT DATABASE (where YOUR app stores results)
# ─────────────────────────────────────────────
# This is a SEPARATE database owned by this app.
# It stores: scan_runs, findings, remediation_scripts, audit_logs.
# Should be a PostgreSQL DB you control.
# The schema is defined in db/schema.sql

AUDIT_DB_URL = os.getenv("AUDIT_DB_URL")


# ─────────────────────────────────────────────
# 5. REPORTS
# ─────────────────────────────────────────────
# Where generated PDF and HTML reports are saved on disk.
# Defaults to reports/output/ inside the project folder.

REPORTS_OUTPUT_PATH = os.getenv(
    "REPORTS_OUTPUT_PATH",
    str(BASE_DIR / "reports" / "output")
)


# ─────────────────────────────────────────────
# 6. ALERTING (Slack + Email)
# ─────────────────────────────────────────────
# Used by scheduler/alerting.py when critical findings are detected.
# All optional — alerting is skipped if these are not set.

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

SMTP_HOST      = os.getenv("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER      = os.getenv("SMTP_USER")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")


# ─────────────────────────────────────────────
# 7. SCAN BEHAVIOR
# ─────────────────────────────────────────────
# Controls how the Scanner Agent behaves on large tables.
#
# SCAN_SCHEDULE_HOURS → how often automated scans run (default: every 6 hours)
# MAX_ROWS_FULL_SCAN  → tables with MORE rows than this get sampled instead
#                       of fully scanned (protects performance on large DBs)
# SAMPLE_SIZE         → how many rows to pull when sampling a large table

SCAN_SCHEDULE_HOURS = int(os.getenv("SCAN_SCHEDULE_HOURS", "6"))
MAX_ROWS_FULL_SCAN  = int(os.getenv("MAX_ROWS_FULL_SCAN",  "500000"))
SAMPLE_SIZE         = int(os.getenv("SAMPLE_SIZE",         "10000"))


# ─────────────────────────────────────────────
# 8. VALIDATION
# ─────────────────────────────────────────────
# Runs at import time. If a critical variable is missing,
# the app raises a clear error immediately instead of
# crashing deep inside an agent with a confusing message.
#
# Only GROK_API_KEY and AUDIT_DB_URL are truly critical —
# without them nothing works at all.
# Target DB URLs are optional because you may only have one DB type.

REQUIRED = {
    "GROK_API_KEY": GROK_API_KEY,
    "AUDIT_DB_URL": AUDIT_DB_URL,
}

missing = [name for name, value in REQUIRED.items() if not value]

if missing:
    raise EnvironmentError(
        f"\n\n[config.py] Missing required environment variables:\n"
        f"  {', '.join(missing)}\n\n"
        f"Fix: add them to your .env file in the project root.\n"
        f"Reference: see .env.example for the full template.\n"
    )


# ─────────────────────────────────────────────
# 9. OPTIONAL: WARN ABOUT MISSING TARGET DBs
# ─────────────────────────────────────────────
# Not a hard crash — just a helpful warning if you haven't
# configured any target database to scan yet.

if not TARGET_CONNECTIONS:
    print(
        "[config.py] WARNING: No target database URLs found.\n"
        "  Set at least one of: POSTGRES_URL, MYSQL_URL, SQLSERVER_URL in .env"
    )