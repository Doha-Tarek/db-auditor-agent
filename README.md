# DB Auditor Agent

AI-powered data quality auditing tool for SQL Server databases. Automatically detects data issues, generates fix scripts, and provides an interactive chat interface for exploring findings.

---

## What it does

- Inspects database schema and detects data quality issues across all tables
- Finds null values, duplicates, outliers, and orphan foreign keys
- Uses an LLM to explain each finding and assign business impact scores
- Generates SQL fix scripts with risk classification
- Requires human approval before executing any fix
- Produces HTML and PDF reports
- Chat interface to ask questions about your data in plain English

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| LLM | Groq API — llama-3.3-70b-versatile |
| Agent Framework | CrewAI |
| Database | SQL Server 2022 (via pyodbc) |
| UI | Streamlit |
| ORM | SQLAlchemy |
| Reports | Jinja2 + WeasyPrint |

---

## Project Structure
db_auditor_agent/

├── agents/

│   ├── schema_inspector.py   # reads DB schema

│   ├── scanner.py            # detects data issues

│   ├── analyst.py            # LLM reasoning

│   ├── reporter.py           # HTML + PDF reports

│   ├── remediator.py         # generates fix SQL

│   └── approval_agent.py     # approve/reject scripts

├── tools/

│   ├── db_connector.py       # DB connections

│   ├── audit_logger.py       # writes to audit DB

│   ├── grok_client.py        # Groq LLM client

│   ├── schema_reader.py      # reads schema snapshots

│   ├── agent_tools.py        # CrewAI tools

│   └── sql_runner.py         # executes approved scripts

├── ui/

│   ├── app.py                # Streamlit entry point

│   └── views/

│       ├── dashboard.py      # findings overview

│       ├── chat.py           # chat with DB

│       ├── approvals.py      # review fix scripts

│       ├── history.py        # scan history & trends

│       └── run_scan.py       # trigger new scan

├── reports/

│   ├── templates/            # Jinja2 HTML templates

│   └── output/               # generated reports

├── prompts/                  # LLM prompt files

├── db/

│   ├── schema.sql            # audit DB schema

│   └── seed_dirty_data.sql   # test data

├── crew.py                   # CrewAI analyst crew

├── main.py                   # CLI pipeline entry point

└── config.py                 # app configuration
---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/Doha-Tarek/db-auditor-agent.git
cd db-auditor-agent
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Configure environment**
```bash
cp .env.example .env
```
Edit `.env` and fill in your Groq API key and SQL Server connection strings.

**4. Set up the audit database**
```bash
sqlcmd -S localhost -d audit_db -i db/schema.sql
```

**5. Seed test data (optional)**
```bash
sqlcmd -S localhost -d target_db -i db/seed_dirty_data.sql
```

---

## Usage

**Run a full scan from CLI:**
```bash
python main.py
```

**Launch the web UI:**
```bash
streamlit run ui/app.py
```

---

## Scan Pipeline
Step 1  Schema Inspection       reads tables, columns, row counts

Step 2  Data Quality Scanning   detects nulls, duplicates, outliers, orphan FKs

Step 3  AI Analysis             LLM explains findings and scores business impact

Step 4  Report Generation       HTML + PDF report saved to reports/output/

Step 5  Remediation Scripts     SQL fixes generated and saved for human review

---

## UI Pages

| Page | Description |
|---|---|
| Dashboard | Overview of findings, quality score, severity breakdown |
| Chat | Ask questions about your data in plain English |
| Approvals | Review and approve or reject SQL fix scripts |
| Scan History | Quality score trends and full scan history |
| Run New Scan | Trigger a new scan from the browser |

---

## Environment Variables

| Variable | Description |
|---|---|
| `GROK_API_KEY` | Groq API key |
| `GROK_MODEL` | LLM model name |
| `SQLSERVER_URL` | Target database connection string |
| `AUDIT_DB_URL` | Audit database connection string |
| `REPORTS_OUTPUT_PATH` | Folder for generated reports |
| `SCAN_SCHEDULE_HOURS` | Hours between automated scans |

---

## Requirements

- Python 3.12
- SQL Server 2022 with ODBC Driver 17
- Groq API key (free tier — 100K tokens/day)
- Windows or Linux
