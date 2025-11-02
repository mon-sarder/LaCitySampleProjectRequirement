# mcp_agent.py
"""
A lightweight "AI Brain" that executes a goal in a single, fast Playwright session,
with a safe HTTP JSON fallback if the browser cannot be launched.

Public API:
  run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> dict
"""

from __future__ import annotations

import re
import json
import asyncio
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# User-Agent reuse
# ──────────────────────────────────────────────────────────────────────────────
try:
    from robot_driver import CUSTOM_UA  # keep UA consistent with driver
except Exception:
    CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"

# ──────────────────────────────────────────────────────────────────────────────
# Optional Playwright (we degrade gracefully if not present)
# ──────────────────────────────────────────────────────────────────────────────
_playwright_ok = True
try:
    from playwright.async_api import async_playwright
except Exception:
    _playwright_ok = False
    async_playwright = None  # type: ignore

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_NAV_TIMEOUT_MS = 8000
HEADLESS_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
]

BASE = "http://localhost:5001"


# ──────────────────────────────────────────────────────────────────────────────
# Small HTTP helpers (fallback path)
# ──────────────────────────────────────────────────────────────────────────────
def _http_get_json(path: str, payload: Optional[dict] = None) -> dict:
    """
    GET (or POST if payload is provided) JSON from the Flask API with the API key header.
    """
    url = path if path.startswith("http") else f"{BASE}{path}"
    headers = {
        "User-Agent": CUSTOM_UA,
        "Accept": "application/json",
        "X-API-Key": "secret123",  # Same default as your Flask app (env can override for prod)
        "Content-Type": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read()
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"status": "error", "message": f"HTTP {e.code} for {url}"}
    except Exception as e:
        return {"status": "error", "message": f"Network error for {url}: {e}"}


# ──────────────────────────────────────────────────────────────────────────────
# Playwright helpers
# ──────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _fast_ctx(headless: bool = True):
    """
    Launch fast Chromium context. If anything fails, re-raise to let caller
    trigger the HTTP fallback path.
    """
    async with async_playwright() as p:  # type: ignore
        browser = await p.chromium.launch(headless=headless, args=HEADLESS_ARGS)
        context = await browser.new_context(user_agent=CUSTOM_UA)
        # set default timeouts (sync APIs on context)
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(DEFAULT_NAV_TIMEOUT_MS)
        page = await context.new_page()
        try:
            yield browser, context, page
        finally:
            await browser.close()


async def _goto(page, url: str):
    await page.goto(url, wait_until="domcontentloaded")


# ──────────────────────────────────────────────────────────────────────────────
# Built-in goal executor
# ──────────────────────────────────────────────────────────────────────────────
async def _builtin_executor_with_browser(goal: str, headless: bool = True) -> Dict[str, Any]:
    """
    Heuristic browser-driven flow:
      - open /search (or /demo)
      - auto-login (admin/admin123) if needed
      - list categories OR search desired category
      - collect first items if present
    """
    goal_l = goal.lower()

    async with _fast_ctx(headless=headless) as (_b, _c, page):
        # Decide landing page
        if "/search" in goal_l:
            target = f"{BASE}/search"
        elif "/demo" in goal_l:
            target = f"{BASE}/demo"
        else:
            target = f"{BASE}/search"

        await _goto(page, target)

        # If login appears, use default admin creds (seeded by app.py on startup)
        try:
            if ("login" in (page.url or "")) or (
                await page.locator('input[name="username"]').count()
                and await page.locator('button[type="submit"]').count()
            ):
                await page.fill('input[name="username"]', "admin")
                await page.fill('input[name="password"]', "admin123")
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("domcontentloaded")
        except Exception:
            # Login is best-effort; continue either way
            pass

        # If user asked to list categories
        if "list categories" in goal_l or "all categories" in goal_l:
            btn = page.locator('button[name="list_all"]')
            if await btn.count():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")

            chips = page.locator(".category-list a")
            cats = [c.strip() for c in await chips.all_inner_texts()] if await chips.count() else []
            return {"status": "success", "agent": "BroncoMCP/1.0", "action": "list_categories", "categories": cats}

        # Extract desired category
        m = re.search(r"(?:category|search)\s+(?:for\s+)?['\"]?([a-zA-Z ]+)['\"]?", goal_l)
        desired = m.group(1).strip() if m else None

        if desired:
            # Use the search bar
            if await page.locator('input[name="query"]').count():
                await page.fill('input[name="query"]', desired)
                if await page.locator('button[type="submit"]').count():
                    await page.click('button[type="submit"]')
                    await page.wait_for_load_state("domcontentloaded")

            # If category chips are shown, click the closest match
            choices = page.locator(".category-list a")
            if await choices.count():
                texts = await choices.all_inner_texts()
                pick_idx = None
                d = desired.lower()
                for idx, t in enumerate(texts):
                    if d in t.lower():
                        pick_idx = idx
                        break
                if pick_idx is None and texts:
                    pick_idx = 0
                if pick_idx is not None:
                    await choices.nth(pick_idx).click()
                    await page.wait_for_load_state("domcontentloaded")

        # Collect items if present
        if await page.locator(".product_pod").count():
            titles = await page.locator(".product_pod h3 a").all_inner_texts()
            prices = await page.locator(".price_color").all_inner_texts()
            items = [{"title": t.strip(), "price": p.strip()} for t, p in zip(titles, prices)]
            return {
                "status": "success",
                "agent": "BroncoMCP/1.0",
                "action": "collect_items",
                "count": len(items),
                "items": items[:5],
            }

        return {"status": "noop", "agent": "BroncoMCP/1.0", "message": "No items found or goal too vague.", "url": page.url}


def _builtin_executor_http_fallback(goal: str) -> Dict[str, Any]:
    """
    No-browser path:
      - If asked to list categories → GET /categories.json
      - Else try to extract a desired category and POST /search-json
    """
    goal_l = goal.lower()

    if "list categories" in goal_l or "all categories" in goal_l:
        res = _http_get_json("/categories.json")
        if res.get("status") == "ok":
            return {"status": "success", "agent": "BroncoMCP/1.0", "action": "list_categories", "categories": res.get("categories", [])}
        return {"status": "error", "agent": "BroncoMCP/1.0", "message": res.get("message", "categories failed")}

    m = re.search(r"(?:category|search)\s+(?:for\s+)?['\"]?([a-zA-Z ]+)['\"]?", goal_l)
    desired = m.group(1).strip() if m else ""
    res = _http_get_json("/search-json", payload={"product": desired})
    # Pass through the server's response (it already returns status / items)
    if isinstance(res, dict):
        res.setdefault("agent", "BroncoMCP/1.0")
        return res
    return {"status": "error", "agent": "BroncoMCP/1.0", "message": "Unexpected response type from /search-json"}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """
    Entry point used by Flask /api/run.
    - Attempts a fast Playwright run first (if available)
    - Falls back to HTTP API calls if Playwright is unavailable or fails
    - Always returns structured JSON
    """
    async def _run() -> Dict[str, Any]:
        if planner != "builtin":
            # Only builtin is supported; keep UX consistent
            pass

        # Try the browser path first when Playwright is present
        if _playwright_ok:
            try:
                return await _builtin_executor_with_browser(goal, headless=headless)
            except Exception as e:
                # Fall through to HTTP fallback with context
                return {
                    "status": "warn",
                    "agent": "BroncoMCP/1.0",
                    "message": f"Playwright path failed, using HTTP fallback: {e}",
                    "fallback": _builtin_executor_http_fallback(goal),
                }

        # If Playwright isn't available, go straight to HTTP fallback
        return _builtin_executor_http_fallback(goal)

    try:
        return asyncio.run(_run())
    except RuntimeError as e:
        # Handles edge cases like "asyncio.run() cannot be called from a running event loop"
        # by switching to a soon-completed task approach.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                coro = _run()
                return loop.run_until_complete(coro)  # type: ignore[func-returns-value]
        except Exception:
            pass
        return {"status": "error", "agent": "BroncoMCP/1.0", "message": f"Async runtime error: {e}"}
    except Exception as e:
        return {"status": "error", "agent": "BroncoMCP/1.0", "message": f"Unhandled error: {e}"}
