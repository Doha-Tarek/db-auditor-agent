# tools/db_connector.py
# Single place for all database connections.
# Every agent imports from here — never create engines anywhere else.

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import config

# ─────────────────────────────────────────────
# 1. ENGINE CACHE
# ─────────────────────────────────────────────
# Engines are expensive to create — we create each one
# once and reuse it everywhere (connection pooling).
# Think of it like keeping a phone line open instead of
# dialing a new number every time.

_engines: dict[str, Engine] = {}


# ─────────────────────────────────────────────
# 2. INTERNAL ENGINE FACTORY
# ─────────────────────────────────────────────
# Creates a new engine or returns the cached one.
# Never call this directly — use the functions below.

def _get_engine(key: str, url: str) -> Engine:
    """
    Returns a cached SQLAlchemy engine for the given URL.
    Creates it on first call, reuses it after that.
    """
    if key not in _engines:
        _engines[key] = create_engine(
            url,
            pool_pre_ping=True,     # tests connection before using it
            pool_size=5,            # keep 5 connections warm
            max_overflow=10,        # allow 10 extra under heavy load
            echo=False              # set True to log all SQL queries
        )
    return _engines[key]


# ─────────────────────────────────────────────
# 3. PUBLIC FUNCTIONS
# ─────────────────────────────────────────────

def get_audit_engine() -> Engine:
    """
    Returns engine for the AUDIT database (audit_db).
    This is OUR app's database — stores findings, scan runs, etc.
    Used by: audit_logger, schema_reader, approval_agent
    """
    if not config.AUDIT_DB_URL:
        raise ValueError(
            "[db_connector] AUDIT_DB_URL is not set in .env"
        )
    return _get_engine("audit", config.AUDIT_DB_URL)


def get_target_engine(db_type: str = "sqlserver") -> Engine:
    """
    Returns engine for the TARGET database (the DB being audited).
    db_type options: 'sqlserver' | 'postgresql' | 'mysql'
    Used by: schema_inspector, scanner
    """
    url_map = {
        "sqlserver":  config.SQLSERVER_URL,
        "postgresql": config.POSTGRES_URL,
        "mysql":      config.MYSQL_URL,
    }

    url = url_map.get(db_type)

    if not url:
        raise ValueError(
            f"[db_connector] No connection URL found for db_type='{db_type}'.\n"
            f"  Make sure {db_type.upper()}_URL is set in your .env file."
        )

    return _get_engine(db_type, url)


# ─────────────────────────────────────────────
# 4. HELPER — TEST ANY CONNECTION
# ─────────────────────────────────────────────
def test_connection(engine: Engine) -> bool:
    """
    Runs a simple SELECT 1 to verify the connection is alive.
    Returns True if healthy, False if something is wrong.
    Used in setup and health checks.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"[db_connector] Connection test failed: {e}")
        return False


# ─────────────────────────────────────────────
# 5. HELPER — GET ALL ACTIVE TARGET CONNECTIONS
# ─────────────────────────────────────────────
def get_all_target_engines() -> dict[str, Engine]:
    """
    Returns engines for ALL configured target databases.
    Useful when scanning multiple DBs in one run.
    Skips any DB type that has no URL configured in .env
    """
    engines = {}
    for db_type, url in config.TARGET_CONNECTIONS.items():
        try:
            engine = _get_engine(db_type, url)
            if test_connection(engine):
                engines[db_type] = engine
                print(f"[db_connector] ✅ {db_type} connected")
            else:
                print(f"[db_connector] ❌ {db_type} connection failed")
        except Exception as e:
            print(f"[db_connector] ❌ {db_type} error: {e}")
    return engines