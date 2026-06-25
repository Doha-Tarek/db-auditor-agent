# tools/grok_client.py
# Single wrapper around the Groq API (free tier).
# Every agent that needs LLM reasoning imports from here.
# Never call the API directly from agents.

import time
import json
from groq import Groq
from tools.audit_logger import logger
import config

# ─────────────────────────────────────────────
# 1. CONSTANTS
# ─────────────────────────────────────────────

MAX_RETRIES = 3    # how many times to retry on failure
RETRY_DELAY = 2    # seconds to wait between retries


# ─────────────────────────────────────────────
# 2. GROQ CLIENT
# ─────────────────────────────────────────────
# Created once and reused — same idea as db connection pooling

def _get_client() -> Groq:
    if not config.GROK_API_KEY:
        raise ValueError("[grok_client] GROK_API_KEY is not set in .env")
    return Groq(api_key=config.GROK_API_KEY)


# ─────────────────────────────────────────────
# 3. CORE FUNCTION — ASK GROK
# ─────────────────────────────────────────────

def ask_grok(
    system_prompt: str,
    user_message:  str,
    temperature:   float = 0.2,
    max_tokens:    int   = None,
) -> str:
    """
    Sends a prompt to Groq and returns the response as a string.
    Automatically retries up to 3 times on failure.

    Args:
        system_prompt: instructions that define how the LLM should behave
        user_message:  the actual question or data to analyze
        temperature:   0.0 = deterministic, 1.0 = creative (default 0.2 for accuracy)
        max_tokens:    max response length (default from config.py)

    Returns:
        LLM response as a plain string.

    Raises:
        RuntimeError if all retries fail.
    """
    tokens = max_tokens or config.GROK_MAX_TOKENS
    client = _get_client()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"llm request | attempt {attempt}/{MAX_RETRIES} | model: {config.GROK_MODEL} | tokens: {tokens}")

            response = client.chat.completions.create(
                model=config.GROK_MODEL,
                temperature=temperature,
                max_tokens=tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message}
                ]
            )

            content = response.choices[0].message.content.strip()
            logger.debug(f"llm response | attempt {attempt} | chars: {len(content)}")
            return content

        except Exception as e:
            error_msg = str(e)
            logger.error(f"llm error | attempt {attempt}/{MAX_RETRIES} | {error_msg}")

            # rate limited — wait longer
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                logger.warning("rate limited — waiting 10 seconds")
                time.sleep(10)
                continue

            # auth error — no point retrying
            if "401" in error_msg or "auth" in error_msg.lower():
                raise RuntimeError("[grok_client] Invalid API key — check your .env file")

        # wait before next retry
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    raise RuntimeError(f"[grok_client] All {MAX_RETRIES} attempts failed. Check logs/app.log for details.")


# ─────────────────────────────────────────────
# 4. JSON RESPONSE HELPER
# ─────────────────────────────────────────────

def ask_grok_json(
    system_prompt: str,
    user_message:  str,
    temperature:   float = 0.1,
    max_tokens:    int   = None,
) -> dict:
    """
    Same as ask_grok() but parses the response as JSON.
    Use this when the prompt instructs the LLM to return JSON.
    Automatically strips markdown code fences if present.

    Returns:
        Parsed dict from the JSON response.

    Raises:
        ValueError if response is not valid JSON.
        RuntimeError if all retries fail.
    """
    raw   = ask_grok(system_prompt, user_message, temperature, max_tokens)
    clean = raw.strip()

    # strip markdown code fences if present
    # e.g. ```json ... ```
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.error(f"llm JSON parse failed | error: {e} | raw: {raw[:200]}")
        raise ValueError(
            f"[grok_client] Response is not valid JSON.\n"
            f"Raw response: {raw[:300]}"
        )


# ─────────────────────────────────────────────
# 5. QUICK TEST HELPER
# ─────────────────────────────────────────────

def test_grok_connection() -> bool:
    """
    Sends a simple ping to verify the API key works.
    Returns True if successful, False if not.
    """
    try:
        response = ask_grok(
            system_prompt="You are a helpful assistant.",
            user_message="Reply with exactly one word: OK",
            max_tokens=10
        )
        success = "ok" in response.lower()
        logger.info(f"llm connection test | {'✅ passed' if success else '❌ unexpected response'} | response: {response}")
        return success
    except Exception as e:
        logger.error(f"llm connection test failed | {e}")
        return False