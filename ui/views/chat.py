# ui/views/chat.py
import streamlit as st
from sqlalchemy import text
from tools.db_connector import get_audit_engine
from tools.grok_client import ask_grok
from tools.schema_reader import get_latest_schema
from pathlib import Path
import html as html_lib


def _load_prompt() -> str:
    path = Path(__file__).resolve().parent.parent.parent / "prompts" / "chat_prompt.txt"
    return path.read_text(encoding="utf-8")


def _build_context(scan_run_id: str, connection_id: str) -> str:
    engine = get_audit_engine()
    schema = get_latest_schema(connection_id)

    with engine.connect() as conn:
        findings = conn.execute(text("""
            SELECT table_name, column_name, issue_type,
                   severity, affected_rows, llm_explanation
            FROM findings WHERE scan_run_id = :scan_id
            ORDER BY CASE severity
                WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                WHEN 'medium'   THEN 3 WHEN 'low'  THEN 4
            END
        """), {"scan_id": scan_run_id}).fetchall()

        scan = conn.execute(text("""
            SELECT overall_score, total_findings, critical_findings
            FROM scan_runs WHERE id = :scan_id
        """), {"scan_id": scan_run_id}).fetchone()

    tables_info = [
        f"- {t}: {', '.join(c['name'] for c in info.get('columns', []))} ({info.get('row_count', 0)} rows)"
        for t, info in schema.get("tables", {}).items()
    ]
    findings_info = [
        f"- [{f[3].upper()}] {f[2]} in {f[0]}{'.' + f[1] if f[1] else ''} ({f[4]} rows){': ' + f[5] if f[5] else ''}"
        for f in findings
    ]

    return f"""DATABASE SCHEMA:
{chr(10).join(tables_info)}

SCAN RESULTS:
Overall Score: {int(scan[0] or 0)}/100
Total Findings: {scan[1]}
Critical: {scan[2]}

FINDINGS:
{chr(10).join(findings_info)}""".strip()


def _get_llm_response(prompt: str, system_prompt: str, context: str) -> str:
    response = ask_grok(
        system_prompt=system_prompt,
        user_message=f"CONTEXT:\n{context}\n\nUSER QUESTION:\n{prompt}",
        max_tokens=400
    )
    # remove backticks that Streamlit renders as colored code
    return response.replace("`", "")


def show(scan_run_id: str = None):

    st.markdown("""
    <style>
    section.main .block-container {
        padding: 2rem 2rem 6rem !important;
        max-width: 100% !important;
    }

    /* chat message cards */
    .chat-user-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .chat-assistant-card {
        background: #ffffff;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .chat-role-user {
        font-size: 11px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: .06em !important;
        color: #2C3E50 !important;
        margin-bottom: 6px !important;
        display: block !important;
    }
    .chat-role-assistant {
        font-size: 11px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: .06em !important;
        color: #6B7280 !important;
        margin-bottom: 6px !important;
        display: block !important;
    }
    .chat-content {
        font-size: 14px !important;
        color: #111827 !important;
        line-height: 1.7 !important;
        font-weight: 400 !important;
    }
    .chat-user-card *, .chat-assistant-card * {
        color: #111827 !important;
    }
    .chat-user-card .chat-role-user {
        color: #2C3E50 !important;
    }
    .chat-assistant-card .chat-role-assistant {
        color: #6B7280 !important;
    }

    /* fix dark bottom input bar */
    [data-testid="stBottom"] {
        background: #F4F5F7 !important;
        border-top: 1px solid #E5E7EB !important;
    }
    [data-testid="stBottom"] > div {
        background: #F4F5F7 !important;
        padding: 12px 32px !important;
    }
    [data-testid="stChatInputContainer"] {
        background: #ffffff !important;
        border: 1px solid #D1D5DB !important;
        border-radius: 10px !important;
    }
    [data-testid="stChatInputContainer"] textarea {
        background: #ffffff !important;
        color: #111827 !important;
        font-size: 14px !important;
    }
    [data-testid="stChatInputContainer"] button {
        background: #2C3E50 !important;
        border-radius: 8px !important;
        border: none !important;
        color: #fff !important;
        width: auto !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if not scan_run_id:
        st.info("Select a scan from the sidebar first.")
        return

    # ── get connection_id ──────────────────────
    engine = get_audit_engine()
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT connection_id FROM scan_runs WHERE id = :sid"
        ), {"sid": scan_run_id}).fetchone()
        if not row:
            st.error("Scan not found.")
            return
        connection_id = str(row[0])

    system_prompt = _load_prompt()
    context       = _build_context(scan_run_id, connection_id)

    # ── session state ──────────────────────────
    if "chat_history"     not in st.session_state:
        st.session_state.chat_history     = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    # ── header ─────────────────────────────────
    st.markdown("""
    <div style="padding:8px 0 24px">
        <h1 style="font-size:32px;font-weight:700;color:#2C3E50;
                   margin:0 0 6px;letter-spacing:-.02em">
            Chat with your Database
        </h1>
        <p style="font-size:13px;color:#6B7280;margin:0">
            Ask anything about your data quality findings in plain English
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── suggested questions ────────────────────
    st.markdown("""
    <div style="font-size:11px;font-weight:600;color:#9CA3AF;
                text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px">
        Suggested questions
    </div>
    """, unsafe_allow_html=True)

    questions = [
        "Which table has the worst data quality?",
        "Why is customer email quality low?",
        "What should I fix first?",
        "Explain the orphan FK issue in orders",
        "How many critical issues do we have?",
        "Suggest fixes for duplicates in customers",
    ]

    c1, c2, c3 = st.columns(3)
    for i, q in enumerate(questions):
        if [c1, c2, c3][i % 3].button(q, key=f"sq_{i}"):
            st.session_state.pending_question = q

    st.markdown(
        "<hr style='border:none;border-top:1px solid #E5E7EB;margin:20px 0'>",
        unsafe_allow_html=True
    )

    # ── handle pending question from buttons ───
    if st.session_state.pending_question:
        q = st.session_state.pending_question
        st.session_state.pending_question = None
        st.session_state.chat_history.append({"role": "user", "content": q})
        try:
            with st.spinner("Thinking..."):
                response = _get_llm_response(q, system_prompt, context)
            st.session_state.chat_history.append({
                "role": "assistant", "content": response
            })
        except Exception as e:
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": f"Something went wrong: {e}"
            })

    # ── render all messages ────────────────────
    for msg in st.session_state.chat_history:
        safe     = html_lib.escape(msg["content"]).replace("\n", "<br>")
        is_user  = msg["role"] == "user"
        card     = "chat-user-card"      if is_user else "chat-assistant-card"
        role_cls = "chat-role-user"      if is_user else "chat-role-assistant"
        label    = "You"                 if is_user else "DB Auditor"

        st.markdown(f"""
        <div class="{card}">
            <span class="{role_cls}">{label}</span>
            <div class="chat-content">{safe}</div>
        </div>
        """, unsafe_allow_html=True)

    # ── chat input ─────────────────────────────
    if prompt := st.chat_input("Ask anything about your database quality..."):
        safe = html_lib.escape(prompt).replace("\n", "<br>")
        st.session_state.chat_history.append({"role": "user", "content": prompt})

        st.markdown(f"""
        <div class="chat-user-card">
            <span class="chat-role-user">You</span>
            <div class="chat-content">{safe}</div>
        </div>
        """, unsafe_allow_html=True)

        with st.spinner("Thinking..."):
            try:
                response = _get_llm_response(prompt, system_prompt, context)
                st.session_state.chat_history.append({
                    "role": "assistant", "content": response
                })
                safe_r = html_lib.escape(response).replace("\n", "<br>")
                st.markdown(f"""
                <div class="chat-assistant-card">
                    <span class="chat-role-assistant">DB Auditor</span>
                    <div class="chat-content">{safe_r}</div>
                </div>
                """, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error: {e}")

    # ── clear chat ─────────────────────────────
    if st.session_state.chat_history:
        if st.button("Clear conversation", key="clear_chat"):
            st.session_state.chat_history = []
            st.rerun()