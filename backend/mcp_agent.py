"""
mcp_agent.py
Robot Driver MCP tools: structured goals, observability, and hardened HTTP helpers.

Exposed tools (via your mcp_bridge):
  - run_goal:       Execute a structured or free-text goal (JSON strongly preferred)
  - search_product: Fast direct search via /search-json
  - list_categories:Return normalized category list with redirect/shape handling
  - ping_metrics:   Fetch server metrics for quick observability

Env knobs (all optional):
  ROBOT_BASE_URL    default http://127.0.0.1:5001
  ROBOT_API_KEY     default secret123
  ROBOT_UA          default "BroncoMCP/1.0 (+https://local) robot-driver"
  ROBOT_TIMEOUT_S   default 12
  ROBOT_MAX_STEPS   default 3
  ROBOT_STEP_DELAY  default 0.15   (seconds between steps)
  ROBOT_RETRIES     default 1      (http retry attempts on failure)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

# --- Configuration -----------------------------------------------------------

API_BASE = os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
API_KEY = os.environ.get("ROBOT_API_KEY", "secret123")
CUSTOM_UA = os.environ.get("ROBOT_UA", "BroncoMCP/1.0 (+https://local) robot-driver")

DEFAULT_TIMEOUT = float(os.environ.get("ROBOT_TIMEOUT_S", 12))
DEFAULT_RETRIES = int(os.environ.get("ROBOT_RETRIES", 1))
MAX_STEPS = int(os.environ.get("ROBOT_MAX_STEPS", 3))
STEP_DELAY = float(os.environ.get("ROBOT_STEP_DELAY", 0.15))

HEADERS = {
    "X-API-Key": API_KEY,
    "User-Agent": CUSTOM_UA,
}

# --- Small utilities ---------------------------------------------------------


def _now_ms() -> int:
    return int(time.time() * 1000)


def _elapsed_ms(t0_ms: int) -> int:
    return _now_ms() - t0_ms


def _normalize_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None values—cleaner payloads."""
    return {k: v for k, v in d.items() if v is not None}


def _http(
    method: str,
    path: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    json_body: Optional[dict] = None,
    allow_redirects: bool = True,
) -> Tuple[bool, Any, int, Dict[str, str]]:
    """
    Thin HTTP helper with retries and uniform return shape.
    Returns: (ok, payload_or_text, status_code, headers)
    """
    url = f"{API_BASE}{path}"
    last_exc: Optional[Exception] = None

    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=HEADERS,
                json=json_body,
                timeout=timeout,
                allow_redirects=allow_redirects,
            )
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json"):
                try:
                    return resp.ok, resp.json(), resp.status_code, dict(resp.headers)
                except requests.exceptions.JSONDecodeError:
                    # Unexpected content-type mismatch
                    return False, {"status": "error", "message": "JSON decode error"}, resp.status_code, dict(resp.headers)
            # Non-JSON; return text so caller can decide
            return resp.ok, resp.text, resp.status_code, dict(resp.headers)
        except Exception as e:
            last_exc = e
            if attempt < max(1, retries) + 1:
                time.sleep(0.2)  # brief backoff

    return False, {"status": "error", "message": str(last_exc)}, 0, {}


def _api_get(path: str, **kwargs) -> Any:
    ok, payload, _, _ = _http("GET", path, **kwargs)
    return payload


def _api_post(path: str, body: Dict[str, Any], **kwargs) -> Any:
    ok, payload, _, _ = _http("POST", path, json_body=body, **kwargs)
    return payload


def _post_metric(event: str, ok: bool, extra: Optional[Dict[str, Any]] = None) -> None:
    """Non-blocking best-effort metric push to /api/metrics (if available)."""
    try:
        payload = _normalize_dict({
            "event": event,
            "ok": ok,
            "ua": CUSTOM_UA,
            "extra": extra or {},
            "ts": _now_ms(),
        })
        _http("POST", "/api/metrics", json_body=payload, timeout=4)
    except Exception:
        pass


# --- Tools -------------------------------------------------------------------
# If you're using an MCP bridge that expects the `@tool` decorator, you can
# keep it. Otherwise, these functions are the tool entry points.


def search_product(query: str, headless: bool = True) -> Dict[str, Any]:
    """
    Fast direct search using server's /search-json endpoint.
    Returns normalized dict: {status, items, meta, agent, timings}
    """
    t0 = _now_ms()
    body = _normalize_dict({"product": query, "headless": headless})
    resp = _api_post("/search-json", body)

    # Normalize common shapes
    status = "error"
    items: List[Dict[str, Any]] = []
    agent = "BroncoMCP/1.0"
    meta = {}

    if isinstance(resp, dict):
        status = resp.get("status", "error")
        agent = resp.get("agent", agent)
        # Common shapes: {"items":[...]}, or {"data":{"items":[...]}}
        if isinstance(resp.get("items"), list):
            items = resp["items"]
        elif isinstance(resp.get("data"), dict) and isinstance(resp["data"].get("items"), list):
            items = resp["data"]["items"]
        meta = resp.get("meta", {})
    elif isinstance(resp, list):
        status = "success"
        items = resp

    ok = status == "success"
    _post_metric("search_product", ok, {"query_len": len(query or ""), "items": len(items)})
    return {
        "status": status,
        "items": items,
        "meta": meta,
        "agent": agent,
        "timings": {"duration_ms": _elapsed_ms(t0)},
    }


def list_categories() -> Dict[str, Any]:
    """
    Returns normalized list of categories.
    Tries /api/categories (preferred JSON, no login redirect); falls back to /categories.json.
    Never raises; returns {"status":"error", "message": "..."} on failures so tools don’t explode.
    """
    # Preferred JSON API
    data = _api_get("/api/categories")

    def _extract(d: Any) -> Optional[List[str]]:
        if isinstance(d, dict):
            if isinstance(d.get("categories"), list):
                return d["categories"]
            if isinstance(d.get("data"), list):
                return d["data"]
            if isinstance(d.get("results"), list):
                return d["results"]
        if isinstance(d, list):
            return d
        return None

    cats = _extract(data)
    if cats is None:
        # Fall back to public JSON
        data = _api_get("/categories.json")
        cats = _extract(data)

    if cats is None:
        _post_metric("list_categories", False, {"reason": "unparsable"})
        return {"status": "error", "message": f"Unable to parse categories payload: {data}"}

    clean = sorted({str(c).strip() for c in cats if c})
    _post_metric("list_categories", True, {"count": len(clean)})
    return {"status": "success", "categories": clean}


def ping_metrics() -> Dict[str, Any]:
    """Return server metrics (if available) for quick observability."""
    data = _api_get("/api/metrics")
    if isinstance(data, dict):
        return {"status": "success", "metrics": data}
    return {"status": "error", "message": "metrics endpoint not available"}


# --- Structured goal runner --------------------------------------------------

def _goal_from_text(text: str) -> Dict[str, Any]:
    """
    Very small heuristic to support free-text goals. Prefer structured JSON goals.
    """
    low = (text or "").lower()
    if "search" in low or "find" in low:
        # naive extraction: last quoted word or last word
        q = ""
        if '"' in text:
            try:
                q = text.split('"')[-2]
            except Exception:
                q = text.split()[-1]
        else:
            q = text.split()[-1]
        return {"intent": "search_product", "query": q}
    # default fallback
    return {"intent": "search_product", "query": text}


def run_ai_goal(
    goal: Any,
    *,
    planner: str = "builtin",
    steps: Optional[int] = None,
    headless: bool = True,
) -> Dict[str, Any]:
    """
    Execute a goal. Prefer JSON like:
      {"intent":"search_product","query":"Travel","steps":2}

    Returns:
      {
        "status": "success"|"error",
        "run_id": "...",
        "result": {...},
        "steps": [ ... ],
        "timings": {"duration_ms": N}
      }
    """
    run_id = str(uuid.uuid4())
    t0 = _now_ms()
    taken_steps: List[Dict[str, Any]] = []
    max_steps = max(1, min(MAX_STEPS, steps or MAX_STEPS))

    # Normalize goal to dict
    if isinstance(goal, str):
        try:
            # Try JSON parse first
            g = json.loads(goal)
        except Exception:
            g = _goal_from_text(goal)
    elif isinstance(goal, dict):
        g = goal
    else:
        g = {"intent": "search_product", "query": str(goal)}

    # Validate length (hardening)
    if len(json.dumps(g)) > 1024:
        _post_metric("run_goal", False, {"reason": "goal too large"})
        return {
            "status": "error",
            "message": "Goal payload is too large.",
            "run_id": run_id,
            "timings": {"duration_ms": _elapsed_ms(t0)},
        }

    intent = (g.get("intent") or "search_product").lower()
    query = g.get("query", "")

    # Main plan (simple built-in)
    for step_idx in range(max_steps):
        step_id = f"{run_id[:8]}-s{step_idx+1}"
        step_t0 = _now_ms()

        if intent == "search_product":
            res = search_product(str(query), headless=headless)
            taken_steps.append({
                "step": step_idx + 1,
                "action": "search_product",
                "ok": res.get("status") == "success",
                "items": len(res.get("items", [])),
                "ms": _elapsed_ms(step_t0),
            })
            time.sleep(max(0.0, STEP_DELAY))
            final = res
            break

        else:
            # Unknown intent → safe error
            taken_steps.append({
                "step": step_idx + 1,
                "action": "unknown_intent",
                "ok": False,
                "intent": intent,
                "ms": _elapsed_ms(step_t0),
            })
            final = {"status": "error", "message": f"unknown intent: {intent}"}
            break

    status_ok = final.get("status") == "success"
    _post_metric("run_goal", status_ok, {"intent": intent, "steps": len(taken_steps)})

    return {
        "status": "success" if status_ok else "error",
        "run_id": run_id,
        "result": final,
        "steps": taken_steps,
        "timings": {"duration_ms": _elapsed_ms(t0)},
        "agent": "BroncoMCP/1.0",
    }


# --- Optional local test -----------------------------------------------------
if __name__ == "__main__":
    # Quick local sanity:
    print("== categories ==")
    print(json.dumps(list_categories(), indent=2))
    print("== search_product Travel ==")
    print(json.dumps(search_product("Travel"), indent=2))
    print("== run_ai_goal(JSON) ==")
    print(json.dumps(run_ai_goal({"intent": "search_product", "query": "Poetry", "steps": 2}), indent=2))
