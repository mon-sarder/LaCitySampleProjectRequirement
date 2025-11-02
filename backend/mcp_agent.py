# mcp_agent.py
import os
import time
import json
import typing as t
import urllib.request
import urllib.error

BASE_URL = os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:5001")
API_KEY  = os.environ.get("API_KEY", "secret123")
UA       = os.environ.get("CUSTOM_UA", "robot-driver/1.0 (MCP Agent)")

DEFAULT_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "8.0"))
RETRY_COUNT = int(os.environ.get("HTTP_RETRIES", "2"))
RETRY_BACKOFF = float(os.environ.get("HTTP_RETRY_BACKOFF", "0.2"))

def _req(method: str, path: str, data: t.Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": UA,
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    last_err = None
    for attempt in range(RETRY_COUNT + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {"status": "error", "message": "Empty response"}
                return json.loads(raw.decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
            else:
                return {"status": "error", "message": str(e), "path": path}
    return {"status": "error", "message": str(last_err), "path": path}

# Public functions used by Claude via MCP tools:
def list_categories() -> dict:
    """Fetch /categories.json, return JSON with 'categories'."""
    return _req("GET", "/categories.json")

def search_product(category_or_term: str) -> dict:
    """POST /search-json with 'product' field."""
    payload = {"product": category_or_term}
    return _req("POST", "/search-json", data=payload)

def run_goal(goal: str, timeout_ms: int = 15000) -> dict:
    """POST /api/run for structured goals ('health', 'list categories', 'search <term>')."""
    payload = {"goal": goal, "timeout_ms": timeout_ms}
    return _req("POST", "/api/run", data=payload)

def metrics() -> dict:
    """GET /api/metrics."""
    return _req("GET", "/api/metrics")

def health() -> dict:
    """GET /api/health."""
    return _req("GET", "/api/health")
