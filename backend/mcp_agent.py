# mcp_agent.py
"""
A lightweight "AI Brain" that executes a goal quickly.

Fast-paths:
- "health" / "status" → return immediately
- "list categories"   → call HTTP /categories.json (no browser)
Fallback:
- Playwright UI executor for search/navigation demos
"""

import os
import re
import time
import asyncio
from typing import Dict, Any
import requests
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright

# Reuse the same UA as robot_driver (falls back if import fails)
try:
    from robot_driver import CUSTOM_UA
except Exception:
    CUSTOM_UA = "BroncoMCP/1.0 (+https://github.com/mon-sarder/LaCitySampleProjectRequirement)"

BASE_API = os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:5001")
API_KEY  = os.environ.get("API_KEY", "secret123")

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_NAV_TIMEOUT_MS = 7000
HEADLESS_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
]

def _ok(data: dict) -> dict:
    data.setdefault("status", "success")
    data.setdefault("agent", "BroncoMCP/1.0")
    return data

def _err(msg: str) -> dict:
    return {"status": "error", "message": msg, "agent": "BroncoMCP/1.0"}

def _get_json(path: str, timeout=12) -> dict:
    url = f"{BASE_API}{path}"
    r = requests.get(url, headers={"X-API-Key": API_KEY, "User-Agent": CUSTOM_UA}, timeout=timeout)
    r.raise_for_status()
    return r.json()

@asynccontextmanager
async def _fast_ctx(headless: bool = True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=HEADLESS_ARGS)
        context = await browser.new_context(user_agent=CUSTOM_UA)
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(DEFAULT_NAV_TIMEOUT_MS)
        page = await context.new_page()
        try:
            yield browser, context, page
        finally:
            await browser.close()

async def _goto(page, url: str):
    await page.goto(url, wait_until="domcontentloaded")

async def _builtin_executor(goal: str, headless: bool = True) -> Dict[str, Any]:
    """
    Heuristic executor for your assignment demo:
      - open /search or /demo
      - log in with default admin if prompted
      - list categories or search for a category
      - return first items if present
    """
    goal_l = goal.lower()
    base = BASE_API

    async with _fast_ctx(headless=headless) as (_b, _c, page):
        # 1) Decide landing page
        if "/search" in goal_l:
            target = f"{base}/search"
        elif "/demo" in goal_l:
            target = f"{base}/demo"
        else:
            target = f"{base}/search"

        await _goto(page, target)

        # 2) If login page appears, use default admin creds
        if "login" in (page.url or "") or (
            await page.locator('input[name="username"]').count()
            and await page.locator('button[type="submit"]').count()
        ):
            try:
                await page.fill('input[name="username"]', "admin")
                await page.fill('input[name="password"]', "admin123")
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("domcontentloaded")
            except Exception:
                pass  # continue anyway

        # 3) list categories if asked
        if "list categories" in goal_l or "all categories" in goal_l:
            # Try to click your UI button if present
            btn = page.locator('button[name="list_all"]')
            if await btn.count():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")
            chips = page.locator(".category-list a")
            cats = [c.strip() for c in await chips.all_inner_texts()] if await chips.count() else []
            return _ok({"action": "list_categories", "categories": cats})

        # 4) extract desired category from goal, e.g., "travel", "science"
        m = re.search(r"(?:category|search)\s+(?:for\s+)?['\"]?([a-zA-Z ]+)['\"]?", goal_l)
        desired = m.group(1).strip() if m else None

        if desired:
            # Try the search bar first
            if await page.locator('input[name="query"]').count():
                await page.fill('input[name="query"]', desired)
                if await page.locator('button[type="submit"]').count():
                    await page.click('button[type="submit"]')
                    await page.wait_for_load_state("domcontentloaded")

            # If the page shows categories, click a closest match
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

        # 5) collect first results if visible
        if await page.locator(".product_pod").count():
            titles = await page.locator(".product_pod h3 a").all_inner_texts()
            prices = await page.locator(".price_color").all_inner_texts()
            items = [{"title": t.strip(), "price": p.strip()} for t, p in zip(titles, prices)]
            return _ok({"action": "collect_items", "count": len(items), "items": items[:5]})

        return {"status": "noop", "message": "No items found or goal too vague.", "url": page.url, "agent": "BroncoMCP/1.0"}


def run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """
    Entry point used by Flask /api/run.
    Prefers fast HTTP paths when possible; falls back to Playwright UI execution.
    """
    t0 = time.time()
    if not goal or not goal.strip():
        return _err("Empty goal.")

    g = goal.lower().strip()

    # Fast-path health/status goals without browser
    if any(k in g for k in ("health", "status", "alive", "ping")):
        return _ok({"message": "Server healthy", "metrics": {"latency_ms": round((time.time()-t0)*1000)}})

    # Fast-path categories without browser
    if "list" in g and "categor" in g:
        try:
            data = _get_json("/categories.json", timeout=10)
            return _ok({"categories": data.get("categories", []), "metrics": {"latency_ms": round((time.time()-t0)*1000)}})
        except Exception as e:
            # Fall back to UI executor if HTTP fails
            pass

    async def _run():
        if planner == "builtin":
            return await _builtin_executor(goal, headless=headless)
        return await _builtin_executor(goal, headless=headless)

    result = asyncio.run(_run())
    if isinstance(result, dict):
        result.setdefault("metrics", {})
        result["metrics"]["latency_ms"] = round((time.time() - t0) * 1000)
        result.setdefault("agent", "BroncoMCP/1.0")
        return result
    return _ok({"output": str(result), "metrics": {"latency_ms": round((time.time()-t0)*1000)}})
