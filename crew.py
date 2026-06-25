# crew.py
# Analyst-only crew — Inspector and Scanner run as pure Python.
# LLM is only used for the Analyst Agent reasoning step.
# This reduces LLM calls from 25+ down to 3-4 total.

import os
import time
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process
from tools.agent_tools import (
    ALL_SCAN_TOOLS,
    set_scan_context,
)
from tools.audit_logger import AuditLogger, logger
from pathlib import Path

# ─────────────────────────────────────────────
# LOAD ENV & SET API KEYS FOR CREWAI/LITELLM
# ─────────────────────────────────────────────
load_dotenv()
os.environ["GROQ_API_KEY"]   = os.getenv("GROK_API_KEY", "")
os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")


# ─────────────────────────────────────────────
# 1. REACT INSTRUCTIONS
# ─────────────────────────────────────────────

REACT_INSTRUCTIONS = """
CRITICAL THINKING INSTRUCTIONS — FOLLOW EXACTLY:

You MUST follow this pattern for EVERY action:

STEP 1 — THINK:
Thought: [What do I need to do next? What tool should I use?]

STEP 2 — ACT:
Action: [tool_name]
Action Input: [input to the tool]

STEP 3 — WAIT:
🛑 STOP and wait for the Observation from the tool.
🛑 NEVER write the Observation yourself.
🛑 NEVER make up tool results.

STEP 4 — OBSERVE:
Observation: [result provided by the tool — NOT written by you]

STEP 5 — REPEAT or CONCLUDE:
If you need more information → go back to STEP 1.
If you have enough information → write your Final Answer.

FINAL ANSWER RULES:
- Only use data from real Observation results
- Never invent findings, row counts, or column names
- If a tool returned an error, report it honestly
- Always cite specific numbers from tool observations
- Never guess — if you don't know, say so

FORBIDDEN:
❌ Writing Observation: yourself
❌ Making up tool results
❌ Skipping the Thought step
❌ Writing Final Answer before using at least one tool
❌ Referencing tables or columns not seen in tool results
"""


# ─────────────────────────────────────────────
# 2. BUILD ANALYST AGENT ONLY
# ─────────────────────────────────────────────

def build_analyst_agent(llm_model: str = "groq/llama-3.3-70b-versatile"):
    """
    Builds only the Analyst Agent.
    Inspector and Scanner run as pure Python — no LLM needed.
    Analyst uses get_scan_summary tool — only 1-2 LLM calls.
    """
    return Agent(
        role="Data Quality Analyst",
        goal=(
            "Analyze all findings from the scanner. "
            "For each finding type explain the problem, root cause, "
            "business impact, and recommended action. "
            "Provide an overall data quality score."
        ),
        backstory=(
            "You are a data analyst.\n"
            "You are a senior data analyst with 15 years of experience.\n"
            "You are a senior data analyst with 15 years of experience "
            "specializing in data quality root cause analysis.\n"
            "You are a senior data analyst with 15 years of experience "
            "specializing in root cause analysis, who always bases conclusions "
            "strictly on the finding data provided — never inventing context.\n"
            "\n"
            + REACT_INSTRUCTIONS
        ),
        tools=[
            ALL_SCAN_TOOLS[7],  # get_scan_summary — only tool analyst needs
        ],
        llm=llm_model,
        verbose=True,
        allow_delegation=False,
        max_iter=3,         # get_summary → analyze → final answer = 3 max
        max_tokens=1000,    # analyst needs tokens for explanations
    )


# ─────────────────────────────────────────────
# 3. BUILD ANALYST TASK
# ─────────────────────────────────────────────

def build_analyst_task(
    analyst_agent,
    scan_run_id:   str,
    findings:      list[dict],
    connection_id: str
) -> Task:
    """
    Builds the analyst task with findings already pre-loaded.
    Findings summary is injected directly so analyst
    doesn't need extra tool calls to fetch them.
    """

    # build compact findings summary to inject into prompt
    by_type = {}
    for f in findings:
        t = f["issue_type"]
        by_type[t] = by_type.get(t, 0) + 1

    findings_summary = "\n".join([
        f"- {issue_type}: {count} findings"
        for issue_type, count in by_type.items()
    ])

    critical = [f for f in findings if f.get("severity") == "critical"]
    high     = [f for f in findings if f.get("severity") == "high"]

    critical_summary = "\n".join([
        f"  CRITICAL: {f['issue_type']} in {f['table']}.{f.get('column', 'entire table')} "
        f"({f['affected_rows']} rows)"
        for f in critical
    ]) or "  None"

    high_summary = "\n".join([
        f"  HIGH: {f['issue_type']} in {f['table']}.{f.get('column', 'entire table')} "
        f"({f['affected_rows']} rows)"
        for f in high[:5]  # limit to first 5 high findings
    ]) or "  None"

    return Task(
        description=f"""
        Analyze the data quality findings from the completed scan.

        SCAN RESULTS ALREADY COLLECTED:
        Total findings: {len(findings)}

        By type:
        {findings_summary}

        Critical findings:
        {critical_summary}

        High severity findings:
        {high_summary}

        INSTRUCTIONS:
        1. Use get_scan_summary to get the complete findings breakdown
        2. For each issue type explain:
           - What the problem means in plain English
           - Most likely root cause
           - Business impact score (1-10)
           - Recommended fix action
        3. Prioritize critical findings first
        4. Give an overall data quality score (0-100)

        CONTEXT:
        - scan_run_id: {scan_run_id}

        STRICT RULES:
        - Only reference findings from get_scan_summary
        - Never invent findings or row counts
        - Base all analysis strictly on tool observations
        - Keep Final Answer structured and concise
        """,
        expected_output=(
            "Analysis of each finding type with root cause, "
            "business impact score, recommended action, "
            "and overall data quality score."
        ),
        agent=analyst_agent,
    )


# ─────────────────────────────────────────────
# 4. RUN ANALYST CREW
# ─────────────────────────────────────────────

def run_analyst_crew(
    connection_id: str,
    scan_run_id:   str,
    findings:      list[dict],
) -> str:
    """
    Runs only the Analyst Agent as a CrewAI crew.
    Inspector and Scanner results are passed in directly.
    Only 2-3 LLM calls total — well within any free tier.
    """
    logger.info(f"analyst crew | starting | findings: {len(findings)}")

    # set context for get_scan_summary tool
    set_scan_context(connection_id, scan_run_id, "sqlserver")

    analyst_agent = build_analyst_agent()
    analyst_task  = build_analyst_task(
        analyst_agent,
        scan_run_id,
        findings,
        connection_id
    )

    crew = Crew(
        agents=[analyst_agent],
        tasks=[analyst_task],
        process=Process.sequential,
        verbose=True,
        max_rpm=10,     # analyst only makes 2-3 calls — plenty of headroom
    )

    # retry up to 3 times
    for attempt in range(1, 4):
        try:
            logger.info(f"analyst crew | attempt {attempt}/3 | kicking off")
            result = crew.kickoff()
            logger.info("analyst crew | completed")
            return result
        except Exception as e:
            error_str = str(e).lower()
            if any(x in error_str for x in ["rate_limit", "429", "quota", "resource_exhausted"]):
                wait = 60 * attempt
                logger.warning(f"analyst crew | rate limit | waiting {wait}s")
                print(f"\n⏳ Rate limit — waiting {wait}s before retry {attempt}/3...\n")
                time.sleep(wait)
            elif any(x in error_str for x in ["503", "unavailable", "high demand"]):
                wait = 30 * attempt
                logger.warning(f"analyst crew | unavailable | waiting {wait}s")
                print(f"\n⏳ Service unavailable — waiting {wait}s before retry {attempt}/3...\n")
                time.sleep(wait)
            else:
                raise e

    raise RuntimeError("analyst crew | all 3 attempts failed")