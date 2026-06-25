-- db/schema.sql
-- Run this once to initialize the audit database.
-- Command: sqlcmd -S localhost -d audit_db -i db/schema.sql

-- ─────────────────────────────────────────────
-- 1. DB CONNECTIONS
-- Stores the list of target databases to audit.
-- ─────────────────────────────────────────────
CREATE TABLE db_connections (
    id              UNIQUEIDENTIFIER    DEFAULT NEWID() PRIMARY KEY,
    name            NVARCHAR(100)       NOT NULL,           -- friendly name e.g. "Production PostgreSQL"
    db_type         NVARCHAR(20)        NOT NULL,           -- postgresql | mysql | sqlserver
    connection_url  NVARCHAR(500)       NOT NULL,           -- full SQLAlchemy connection string
    is_active       BIT                 DEFAULT 1,          -- 1 = active, 0 = disabled
    created_at      DATETIME2           DEFAULT GETDATE()
);

-- ─────────────────────────────────────────────
-- 2. SCAN RUNS
-- One row per scan execution.
-- ─────────────────────────────────────────────
CREATE TABLE scan_runs (
    id                  UNIQUEIDENTIFIER    DEFAULT NEWID() PRIMARY KEY,
    connection_id       UNIQUEIDENTIFIER    REFERENCES db_connections(id),
    started_at          DATETIME2           DEFAULT GETDATE(),
    completed_at        DATETIME2           NULL,               -- NULL means still running
    status              NVARCHAR(20)        DEFAULT 'pending',  -- pending | running | completed | failed
    triggered_by        NVARCHAR(20)        DEFAULT 'manual',   -- manual | schedule | event | threshold
    overall_score       FLOAT               NULL,               -- quality score 0-100
    total_findings      INT                 DEFAULT 0,
    critical_findings   INT                 DEFAULT 0,
    error_message       NVARCHAR(MAX)       NULL                -- filled if status = failed
);

-- ─────────────────────────────────────────────
-- 3. SCHEMA SNAPSHOTS
-- Stores the DB schema as JSON after each inspection.
-- ─────────────────────────────────────────────
CREATE TABLE schema_snapshots (
    id              UNIQUEIDENTIFIER    DEFAULT NEWID() PRIMARY KEY,
    connection_id   UNIQUEIDENTIFIER    REFERENCES db_connections(id),
    scan_run_id     UNIQUEIDENTIFIER    REFERENCES scan_runs(id),
    schema_json     NVARCHAR(MAX)       NOT NULL,   -- full schema as JSON
    table_count     INT                 DEFAULT 0,
    captured_at     DATETIME2           DEFAULT GETDATE()
);

-- ─────────────────────────────────────────────
-- 4. FINDINGS
-- One row per anomaly detected.
-- ─────────────────────────────────────────────
CREATE TABLE findings (
    id                  UNIQUEIDENTIFIER    DEFAULT NEWID() PRIMARY KEY,
    scan_run_id         UNIQUEIDENTIFIER    REFERENCES scan_runs(id),
    table_name          NVARCHAR(128)       NOT NULL,
    column_name         NVARCHAR(128)       NULL,           -- NULL for table-level findings
    issue_type          NVARCHAR(50)        NOT NULL,       -- null | duplicate | outlier | orphan_fk | distribution
    severity            NVARCHAR(20)        NOT NULL,       -- critical | high | medium | low | info
    affected_rows       INT                 DEFAULT 0,
    total_rows          INT                 DEFAULT 0,
    affected_percent    FLOAT               DEFAULT 0,      -- affected_rows / total_rows * 100
    llm_explanation     NVARCHAR(MAX)       NULL,           -- Grok natural language explanation
    root_cause          NVARCHAR(MAX)       NULL,           -- Grok root cause analysis
    business_impact     INT                 DEFAULT 0,      -- 1-10 score from Grok
    confidence_score    FLOAT               DEFAULT 0,      -- agent confidence 0.0 - 1.0
    created_at          DATETIME2           DEFAULT GETDATE()
);

-- ─────────────────────────────────────────────
-- 5. REMEDIATION SCRIPTS
-- One row per generated fix SQL script.
-- ─────────────────────────────────────────────
CREATE TABLE remediation_scripts (
    id                  UNIQUEIDENTIFIER    DEFAULT NEWID() PRIMARY KEY,
    finding_id          UNIQUEIDENTIFIER    REFERENCES findings(id),
    sql_script          NVARCHAR(MAX)       NOT NULL,       -- the generated SQL fix
    risk_level          NVARCHAR(20)        NOT NULL,       -- safe | moderate | destructive
    explanation         NVARCHAR(MAX)       NULL,           -- what this script does in plain English
    status              NVARCHAR(20)        DEFAULT 'pending', -- pending | approved | rejected | executed
    approved_by         NVARCHAR(100)       NULL,           -- username who approved
    approved_at         DATETIME2           NULL,
    executed_at         DATETIME2           NULL,
    execution_result    NVARCHAR(MAX)       NULL,           -- success message or error
    created_at          DATETIME2           DEFAULT GETDATE()
);

-- ─────────────────────────────────────────────
-- 6. AUDIT LOG
-- Logs every important action in the system.
-- ─────────────────────────────────────────────
CREATE TABLE audit_log (
    id              UNIQUEIDENTIFIER    DEFAULT NEWID() PRIMARY KEY,
    event_type      NVARCHAR(50)        NOT NULL,       -- scan_started | finding_detected | script_approved | script_executed
    entity_type     NVARCHAR(50)        NULL,           -- scan_run | finding | remediation_script
    entity_id       UNIQUEIDENTIFIER    NULL,           -- ID of the related row
    message         NVARCHAR(MAX)       NULL,           -- human readable description
    performed_by    NVARCHAR(100)       NULL,           -- user or agent name
    created_at      DATETIME2           DEFAULT GETDATE()
);

-- ─────────────────────────────────────────────
-- 7. INDEXES
-- Speed up the most common queries.
-- ─────────────────────────────────────────────

-- scan_runs: quickly find all scans for a connection
CREATE INDEX idx_scan_runs_connection
ON scan_runs(connection_id);

-- findings: quickly find all findings for a scan
CREATE INDEX idx_findings_scan_run
ON findings(scan_run_id);

-- findings: quickly find findings by severity
CREATE INDEX idx_findings_severity
ON findings(severity);

-- findings: quickly find findings by table name
CREATE INDEX idx_findings_table
ON findings(table_name);

-- remediation_scripts: quickly find pending scripts
CREATE INDEX idx_remediation_status
ON remediation_scripts(status);

-- audit_log: quickly find logs by event type
CREATE INDEX idx_audit_log_event
ON audit_log(event_type);

-- ─────────────────────────────────────────────
-- 8. SEED: DEFAULT DB CONNECTION
-- Inserts target_db as the first connection to audit.
-- ─────────────────────────────────────────────
INSERT INTO db_connections (name, db_type, connection_url)
VALUES (
    'Local SQL Server - target_db',
    'sqlserver',
    'mssql+pyodbc://localhost/target_db?driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes'
);