# ui/app.py
# Main Streamlit app entry point.
# Run with: streamlit run ui/app.py

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ── add project root to path ───────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
os.environ["GROQ_API_KEY"]   = os.getenv("GROK_API_KEY", "")
os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")

import streamlit as st
from sqlalchemy import text
from tools.db_connector import get_audit_engine

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="AI Data Quality Auditor",
    page_icon="assets/logo.png" if Path("assets/logo.png").exists() else None,
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# GLOBAL CSS
# ─────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', sans-serif !important;
    background: #F4F5F7 !important;
}

/* ── sidebar ── */
[data-testid="stSidebar"] {
    background: #2C3E50 !important;
    border-right: none !important;
}
[data-testid="stSidebar"] * {
    color: #fff !important;
}

/* fix selectbox white background in sidebar */
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(255,255,255,0.15) !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] span {
    color: #fff !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] svg {
    fill: #fff !important;
}

/* sidebar buttons */
[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    color: #fff !important;
    width: 100% !important;
    text-align: left !important;
    border-radius: 6px !important;
    padding: 9px 14px !important;
    margin-bottom: 4px !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    transition: background .15s !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.14) !important;
}

/* ── main content ── */
section.main > div { padding-top: 0 !important; }

/* ── hide streamlit branding ── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────

if "page"         not in st.session_state: st.session_state.page         = "dashboard"
if "scan_run_id"  not in st.session_state: st.session_state.scan_run_id  = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="padding:4px 0 20px">
        <div style="width:32px;height:32px;background:#fff;border-radius:6px;
                    display:flex;align-items:center;justify-content:center;margin-bottom:10px">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <rect x="2" y="2" width="6" height="6" rx="1.5" fill="#2C3E50"/>
                <rect x="10" y="2" width="6" height="6" rx="1.5" fill="#2C3E50" opacity=".4"/>
                <rect x="2" y="10" width="6" height="6" rx="1.5" fill="#2C3E50" opacity=".4"/>
                <rect x="10" y="10" width="6" height="6" rx="1.5" fill="#2C3E50" opacity=".7"/>
            </svg>
        </div>
        <div style="font-size:14px;font-weight:600;color:#fff">DB Auditor</div>
        <div style="font-size:11px;color:rgba(255,255,255,.45);margin-top:2px">
            AI Data Quality Agent
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:10px;font-weight:600;color:rgba(255,255,255,.35);'
        'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Overview</div>',
        unsafe_allow_html=True
    )
    if st.button("Dashboard"):
        st.session_state.page = "dashboard"
    if st.button("Chat with DB"):
        st.session_state.page = "chat"

    st.markdown(
        '<div style="font-size:10px;font-weight:600;color:rgba(255,255,255,.35);'
        'text-transform:uppercase;letter-spacing:.08em;margin:12px 0 6px">Actions</div>',
        unsafe_allow_html=True
    )
    if st.button("Approvals"):
        st.session_state.page = "approvals"
    if st.button("Scan History"):
        st.session_state.page = "history"

    st.markdown(
        "<hr style='border-color:rgba(255,255,255,.1);margin:16px 0'>",
        unsafe_allow_html=True
    )
    if st.button("Run New Scan"):
        st.session_state.page = "run_scan"

    st.markdown(
        "<hr style='border-color:rgba(255,255,255,.1);margin:16px 0'>",
        unsafe_allow_html=True
    )

    # ── scan selector ──────────────────────────
    try:
        engine = get_audit_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT TOP 5 id, started_at, overall_score, total_findings, status
                FROM scan_runs
                ORDER BY started_at DESC
            """)).fetchall()

        if rows:
            st.markdown(
                '<div style="font-size:10px;font-weight:600;color:rgba(255,255,255,.35);'
                'text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Recent scans</div>',
                unsafe_allow_html=True
            )
            options = {
                f"{str(r[0])[:8].upper()} — score {int(r[2] or 0)} — {r[4]}": str(r[0])
                for r in rows
            }
            selected = st.selectbox(
                "scan",
                list(options.keys()),
                label_visibility="collapsed"
            )
            st.session_state.scan_run_id = options[selected]
    except Exception as e:
        st.error(f"DB error: {e}")

# ─────────────────────────────────────────────
# PAGE ROUTING
# ─────────────────────────────────────────────

page = st.session_state.page

if page == "dashboard":
    from ui.views.dashboard import show
    show(st.session_state.scan_run_id)

elif page == "chat":
    from ui.views.chat import show
    show(st.session_state.scan_run_id)

elif page == "approvals":
    from ui.views.approvals import show
    show(st.session_state.scan_run_id)

elif page == "history":
    from ui.views.history import show
    show()

elif page == "run_scan":
    from ui.views.run_scan import show
    show()