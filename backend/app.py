# app.py
import os
import time
import json
import traceback
from typing import Dict, Any, List

from flask import Flask, jsonify, request, make_response
from werkzeug.exceptions import BadRequest

# ---- Optional: import your Playwright robot if present ----
# If not present, the code automatically falls back to a stub.
try:
    from robot_driver import search_product as robot_search_product  # noqa: F401
    HAS_ROBOT = True
except Exception:
    HAS_ROBOT = False

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY", "secret123")
CUSTOM_UA = os.environ.get(
    "CUSTOM_UA",
    "robot-driver/1.0 (Mac; MCP) Python/Flask"
)

# Expose a stable category cache (Claude relies on this being fast + deterministic)
DEFAULT_CATEGORIES: List[str] = [
    "Travel", "Mystery", "Historical Fiction", "Sequential Art", "Classics",
    "Philosophy", "Romance", "Womens Fiction", "Fiction", "Childrens",
    "Religion", "Nonfiction", "Music", "Sports and Games", "Add a comment",
    "Fantasy", "New Adult", "Young Adult", "Science Fiction", "Poetry",
    "Paranormal", "Art", "Psychology", "Autobiography", "Parenting",
    "Adult Fiction", "Humor", "Horror", "History", "Food and Drink",
    "Christian Fiction", "Business", "Biography", "Thriller", "Contemporary",
    "Spirituality", "Academic", "Self Help", "Historical", "Christian",
    "Suspense", "Short Stories", "Novels", "Health", "Politics",
    "Cultural", "Science", "Crime", "Computers", "Default"
]

# -----------------------------------------------------------------------------
# App init
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def require_api_key() -> None:
    """Abort with 401 if the X-API-Key is missing or wrong."""
    key = request.headers.get("X-API-Key")
    if key != API_KEY:
        resp = jsonify({"status": "error", "message": "Unauthorized"})
        return make_response(resp, 401)

def ok(data: Dict[str, Any], code: int = 200):
    resp = jsonify(data)
    return make_response(resp, code)

def err(message: str, code: int = 400, extra: Dict[str, Any] | None = None):
    payload = {"status": "error", "message": message}
    if extra:
        payload.update(extra)
    return make_response(jsonify(payload), code)

def list_categories() -> List[str]:
    # In a real build this might fetch and cache from the BooksToScrape site.
    return DEFAULT_CATEGORIES

def safe_robot_search(category: str) -> Dict[str, Any]:
    """Wrapper that calls your Playwright robot if available; otherwise a stub."""
    try:
        if HAS_ROBOT:
            from robot_driver import search_product  # import inside to avoid cold-start cost
            result = search_product(category or "")
            # Normalize minimal contract
            return {
                "status": result.get("status", "success"),
                "title": result.get("title"),
                "price": result.get("price"),
                "category": category,
                "meta": result.get("meta", {}),
            }
        # Stub result for local dev
        return {
            "status": "success",
            "title": f"Sample item in {category or 'All'}",
            "price": "£42.00",
            "category": category or "All",
            "meta": {"note": "stubbed result (robot unavailable)"},
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# -----------------------------------------------------------------------------
# Middlewares (simple, header-based auth for API)
# -----------------------------------------------------------------------------
@app.before_request
def _auth_gate():
    # Only protect API/JSON routes; allow the UI or static if you serve one.
    api_like = request.path.startswith("/api/") or request.path.endswith(".json")
    if api_like:
        unauthorized = require_api_key()
        if unauthorized is not None:
            return unauthorized  # 401

# -----------------------------------------------------------------------------
# Health + Metrics
# -----------------------------------------------------------------------------
START_TS = time.time()
REQ_COUNTER = {"api": 0, "ui": 0}

def _count(path: str):
    if path.startswith("/api/") or path.endswith(".json"):
        REQ_COUNTER["api"] += 1
    else:
        REQ_COUNTER["ui"] += 1

@app.after_request
def _count_resp(resp):
    _count(request.path or "")
    # Keep the response JSON-only for API-like routes
    if request.path.startswith("/api/") or request.path.endswith(".json"):
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["X-Server-UA"] = CUSTOM_UA
    return resp

@app.get("/api/health")
def api_health():
    return ok({
        "status": "ok",
        "agent": "BroncoMCP/1.0",
        "has_robot": HAS_ROBOT,
        "categories_cached": len(DEFAULT_CATEGORIES)
    })

@app.get("/api/metrics")
def api_metrics():
    return ok({
        "status": "success",
        "uptime_seconds": int(time.time() - START_TS),
        "requests": REQ_COUNTER
    })

# -----------------------------------------------------------------------------
# Categories + Search (JSON, strict)
# -----------------------------------------------------------------------------
@app.get("/categories.json")
def categories_json():
    cats = list_categories()
    return ok({"status": "success", "count": len(cats), "categories": cats})

@app.post("/search-json")
def search_json():
    try:
        data = request.get_json(force=True) or {}
    except BadRequest:
        return err("Invalid JSON body.", 400)
    category = (data.get("product") or data.get("category") or "").strip()
    result = safe_robot_search(category)
    # Guarantee a non-empty JSON body
    if not result:
        return err("Empty search result.", 500)
    return ok(result)

# -----------------------------------------------------------------------------
# Robust /api/run goal router (Fixes your 500s)
# -----------------------------------------------------------------------------
@app.post("/api/run")
def api_run():
    """
    Accepts JSON:
      {
        "goal": "list categories" | "health" | "search <term/category>",
        "timeout_ms": 15000   # optional
      }
    Returns structured JSON and never raw HTML.
    """
    t0 = time.time()
    try:
        payload = request.get_json(force=True) or {}
    except BadRequest:
        return err("Invalid JSON payload.", 400)

    goal = (payload.get("goal") or "").strip().lower()
    timeout_ms = int(payload.get("timeout_ms") or 15000)

    if not goal:
        return err("Missing 'goal' field.", 400)

    try:
        if "health" in goal:
            result = {
                "status": "success",
                "agent": "BroncoMCP/1.0",
                "has_robot": HAS_ROBOT,
                "categories_cached": len(DEFAULT_CATEGORIES)
            }

        elif "list" in goal and "categor" in goal:
            cats = list_categories()
            result = {"status": "success", "categories": cats, "count": len(cats)}

        elif goal.startswith("search"):
            # naive parsing: "search travel", "search romance"
            parts = goal.split()
            query = " ".join(parts[1:]) if len(parts) > 1 else ""
            result = safe_robot_search(query)

        else:
            # fallback: return a friendly message
            result = {
                "status": "success",
                "message": f"No built-in handler for goal '{goal}'. "
                           f"Try 'health', 'list categories', or 'search <term>'."
            }

        latency = int((time.time() - t0) * 1000)
        return ok({"status": "success", "goal": goal, "latency_ms": latency, "result": result})

    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return err("Goal execution failed.",
                   500,
                   {"latency_ms": latency, "detail": str(e), "trace": traceback.format_exc()})

# -----------------------------------------------------------------------------
# Error handlers (always JSON for API-like paths)
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def _404(_e):
    if request.path.startswith("/api/") or request.path.endswith(".json"):
        return err("Not found", 404)
    # if you also serve HTML pages, you can render a template here
    return err("Not found", 404)

@app.errorhandler(500)
def _500(_e):
    # We avoid leaking stack traces; use metrics/log files for deep debug
    return err("Internal Server Error", 500)

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Local run: `API_KEY=secret123 python app.py`
    app.run(host="0.0.0.0", port=5001, debug=False)
