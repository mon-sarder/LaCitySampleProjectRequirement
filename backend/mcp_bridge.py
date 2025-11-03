# mcp_bridge.py
# Minimal MCP server that exposes your HTTP API as MCP tools for Claude.
import os
import json
import requests
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("ROBOT_BASE_URL", "http://localhost:5001")
API_KEY = os.environ.get("ROBOT_API_KEY", "secret123")

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY

app = FastMCP("RobotDriver")


@app.tool()
def check_health() -> dict:
    """
    Check the /api/health endpoint directly.
    Returns server health status.
    """
    url = f"{BASE_URL}/api/health"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Health check failed: {str(e)}"
        }


@app.tool()
def run_goal(goal: str, planner: str = "builtin") -> dict:
    """
    Execute a high-level goal via the /api/run endpoint.
    Returns JSON with status/result.
    """
    url = f"{BASE_URL}/api/run"
    payload = {"goal": goal, "planner": planner}
    try:
        r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=120)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Goal execution failed: {str(e)}"
        }


@app.tool()
def search_product(product: str, limit: int = 10) -> dict:
    """
    Call /search-json to run the Playwright 'search product' flow.

    Args:
        product: The category or product name to search for
        limit: Maximum number of results to return (default: 10, max: 50)

    Returns:
        JSON response with search results including items, status, and metadata
    """
    url = f"{BASE_URL}/search-json"

    # Enforce reasonable limits (max 50 items)
    if limit < 1:
        limit = 10
    elif limit > 50:
        limit = 50

    payload = {"product": product, "limit": limit}
    try:
        r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Search failed: {str(e)}",
            "items": []
        }


@app.tool()
def list_categories() -> dict:
    """
    Return available categories from /categories.json.
    """
    url = f"{BASE_URL}/categories.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Failed to list categories: {str(e)}",
            "categories": []
        }


if __name__ == "__main__":
    # Runs an MCP server over stdio for Claude Desktop.
    app.run()