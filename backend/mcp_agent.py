"""
mcp_agent.py
Lightweight MCP client helpers for Claude tools.

- Uses the same API key header as the server (X-API-Key)
- Shares a custom User-Agent
- Provides list_categories, search_product, run_ai_goal
- Has graceful fallbacks and clear error messages
"""

import os
import time
from typing import Dict, Any, List, Optional

import requests

# ---- Config
BASE_URL = os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:5001")
API_KEY = os.environ.get("ROBOT_API_KEY", "secret123")

CUSTOM_UA = (
    os.environ.get("CUSTOM_UA")
    or "BroncoMCP/1.0 (+http://localhost; robot-driver)"
)

TIMEOUT = float(os.environ.get("MCP_HTTP_TIMEOUT", "20"))
RETRIES = int(os.environ.get("MCP_HTTP_RETRIES", "2"))

HEADERS = {
    "User-Agent": CUSTOM_UA,
    "X-API-Key": API_KEY,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def _request_json(method: str, path: str, json: Optional[dict] = None) -> Dict[str, Any]:
    url = path if path.startswith("http") else f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    last_err = None
    for _ in range(RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=HEADERS, json=json, timeout=TIMEOUT)
            # Ensure we return JSON (even if status != 200)
            try:
                body = resp.json()
            except Exception:
                body = {"status": "error", "message": "Non-JSON response", "text": resp.text[:500]}
            body["_http_status"] = resp.status_code
            return body
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    return {"status": "error", "message": f"HTTP {method} {url} failed: {last_err}"}

# ---- Public API

def list_categories() -> Dict[str, Any]:
    """
    Returns categories from /categories.json.
    Always returns JSON; server enforces a non-empty fallback.
    """
    return _request_json("GET", "/categories.json")

def search_product_api(product: str) -> Dict[str, Any]:
    """
    POST /search-json {product}
    """
    payload = {"product": product}
    return _request_json("POST", "/search-json", json=payload)

def run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """
    POST /api/run
    """
    payload = {"goal": goal, "planner": planner, "headless": bool(headless), "plan": []}
    return _request_json("POST", "/api/run", json=payload)

# ---- Convenience
if __name__ == "__main__":
    print("Health:", _request_json("GET", "/api/health"))
    print("Categories:", list_categories())
    print("Demo search:", search_product_api("travel"))
