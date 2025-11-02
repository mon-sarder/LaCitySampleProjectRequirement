# mcp_agent.py
"""
MCP Agent: fast, observable, and resilient.

- Structured goals: accepts either a plain string or a structured dict:
    {"intent": "search_product", "query": "travel"}
  (You can add more intents later.)

- Speed tuners via env:
    PW_HEADLESS      = "1" | "0"         (default: 1)
    CLICK_DELAY_MS   = int (default: 0)
    NAV_TIMEOUT_MS   = int (default: 10000)
    MAX_STEPS        = int (default: 3)

- Observability:
    returns a full result object with:
        run_id, timings, steps, logs, status, error (if any)

- Hardening:
    input validation, bounded steps, default timeouts, and defensive
    try/except around all robot calls.

Note: This agent uses your existing robot_driver.search_product(). It
doesn't require OpenAI or external LLMs for now ('builtin' planner).
"""

from __future__ import annotations
import os
import time
import uuid
import traceback
from typing import Dict, Any, List, Tuple

# Your Playwright driver
import robot_driver as rd  # must expose search_product(query: str) -> dict
from robot_driver import search_product as _search_product

# ---------- Speed Tuners (env) ----------
PW_HEADLESS   = os.environ.get("PW_HEADLESS", "1").lower() in ("1", "true", "yes")
CLICK_DELAY   = int(os.environ.get("CLICK_DELAY_MS", "0"))       # ms
NAV_TIMEOUT   = int(os.environ.get("NAV_TIMEOUT_MS", "10000"))   # ms
MAX_STEPS     = int(os.environ.get("MAX_STEPS", "3"))
CUSTOM_UA     = os.environ.get(
    "CUSTOM_UA",
    "BroncoMCP/1.0 (+local; Playwright bot) AppleWebKit/537.36"
)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _ok(result: Dict[str, Any], step_logs: List[Dict[str, Any]], run_id: str,
        t0: int) -> Dict[str, Any]:
    return {
        "status": "success",
        "agent": "BroncoMCP/1.0",
        "run_id": run_id,
        "timings": {
            "started_ms": t0,
            "ended_ms": _now_ms(),
            "duration_ms": _now_ms() - t0,
        },
        "steps": step_logs,
        "result": result,
    }

def _err(message: str, step_logs: List[Dict[str, Any]], run_id: str,
         t0: int, exc: Exception | None = None) -> Dict[str, Any]:
    payload = {
        "status": "error",
        "agent": "BroncoMCP/1.0",
        "run_id": run_id,
        "message": message,
        "timings": {
            "started_ms": t0,
            "ended_ms": _now_ms(),
            "duration_ms": _now_ms() - t0,
        },
        "steps": step_logs,
    }
    if exc:
        payload["trace"] = traceback.format_exc().splitlines()[-12:]
    return payload

def _parse_goal(goal: Any) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (intent, params)
    Supported:
      - string goal -> ("search_product", {"query": goal})
      - dict goal with {"intent": "...", "query": "..."}
    """
    if isinstance(goal, dict):
        intent = str(goal.get("intent", "search_product")).strip().lower()
        params = {k: v for k, v in goal.items() if k != "intent"}
        return intent, params

    # Fallback: plain string
    g = (goal or "").strip()
    return "search_product", {"query": g}

def _bounded_steps(n: int) -> int:
    try:
        n = int(n)
    except Exception:
        n = 1
    return max(1, min(n, MAX_STEPS))

def _call_search(query: str, step_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Wraps the existing robot_driver.search_product with timing and UA/timeout
    hints where possible. Your robot_driver may ignore extras; that’s fine.
    """
    step_t0 = _now_ms()
    meta = {
        "user_agent": CUSTOM_UA,
        "headless": PW_HEADLESS,
        "click_delay_ms": CLICK_DELAY,
        "nav_timeout_ms": NAV_TIMEOUT,
    }
    try:
        # If your robot_driver.search_product accepts kwargs, they'll be used.
        # If not, Python will complain—so try kwargs then fallback to positional.
        try:
            result = _search_product(query=query, **meta)
        except TypeError:
            # Older signature: search_product(query: str)
            result = _search_product(query)

        step_logs.append({
            "name": "search_product",
            "query": query,
            "meta": meta,
            "started_ms": step_t0,
            "ended_ms": _now_ms(),
            "duration_ms": _now_ms() - step_t0,
            "status": result.get("status", "unknown"),
        })
        return result
    except Exception as e:
        step_logs.append({
            "name": "search_product",
            "query": query,
            "meta": meta,
            "started_ms": step_t0,
            "ended_ms": _now_ms(),
            "duration_ms": _now_ms() - step_t0,
            "status": "error",
            "error": str(e),
        })
        raise

def _builtin_planner(goal: Any, headless: bool) -> Dict[str, Any]:
    """
    Simple non-LLM executor:
      - Parses intent
      - Executes up to MAX_STEPS bounded actions (currently just search).
    """
    t0 = _now_ms()
    run_id = str(uuid.uuid4())
    step_logs: List[Dict[str, Any]] = []

    try:
        intent, params = _parse_goal(goal)
        if intent not in ("search_product",):
            return _err(f"Unsupported intent '{intent}'", step_logs, run_id, t0, None)

        q = str(params.get("query", "")).strip()
        if not q:
            return _err("Missing 'query' for search_product.", step_logs, run_id, t0, None)

        # bounded execution
        steps = _bounded_steps(params.get("steps", 1))
        last = {}
        for _ in range(steps):
            last = _call_search(q, step_logs)
            # if we succeeded, stop early
            if last.get("status") == "success":
                break
        return _ok(last, step_logs, run_id, t0)

    except Exception as e:
        return _err(f"Planner failed: {e}", step_logs, run_id, t0, e)

def run_ai_goal(goal: Any, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """
    Public entry used by /api/run.
    - goal: string or dict
    - planner: currently "builtin" (no external LLMs).
    - headless: kept for API parity; we also read PW_HEADLESS env.

    Returns structured dict (see _ok/_err above).
    """
    # For now we only support the built-in non-LLM planner
    return _builtin_planner(goal=goal, headless=headless)
