# mcp_bridge.py
# Minimal MCP server that exposes your HTTP API as MCP tools for Claude.
import os
import json
import requests
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("ROBOT_BASE_URL", "http://localhost:5001")
API_KEY  = os.environ.get("ROBOT_API_KEY", "secret123")

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY

app = FastMCP("RobotDriver")

@app.tool()
def run_goal(goal: str, planner: str = "builtin") -> dict:
    """
    Execute a high-level goal via the /api/run endpoint.
    Returns JSON with status/result.
    """
    url = f"{BASE_URL}/api/run"
    payload = {"goal": goal, "planner": planner}
    r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=120)
    r.raise_for_status()
    return r.json()

@app.tool()
def search_product(product: str) -> dict:
    """
    Call /search-json to run the Playwright 'search product' flow.
    """
    url = f"{BASE_URL}/search-json"
    payload = {"product": product}
    r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=60)
    r.raise_for_status()
    return r.json()

@app.tool()
def list_categories() -> dict:
    """
    Return available categories from /categories.json.
    """
    url = f"{BASE_URL}/categories.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    # Runs an MCP server over stdio for Claude Desktop.
    app.run()
