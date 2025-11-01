# mcp_agent.py
"""
A lightweight "AI Brain" that executes a goal in a single, fast Playwright session.

This module is intentionally minimal and speed-tuned:
- Headless Chromium with slim flags
- Tight timeouts (3s / 5s)
- domcontentloaded navigation
- Batches steps rather than many tool calls

Public API:
  - run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> dict
"""

import re
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any

from playwright.async_api import async_playwright

# Reuse the same UA as robot_driver; fall back if not importable.
try:
    from robot_driver import CUSTOM_UA
except Exception:
    CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_NAV_TIMEOUT_MS = 7000
HEADLESS_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
]


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


# ---------------------- Builtin goal executor ----------------------

async def _builtin_executor(goal: str, headless: bool = True) -> Dict[str, Any]:
    """
    Heuristic executor that handles common goals for your assignment:
      - open /demo or /search
      - list categories
      - search a category
      - return first N items
    """
    goal_l = goal.lower()

    async with _fast_ctx(headless=headless) as (_b, _c, page):
        base = "http://localhost:5001"

        # 1) decide landing page
        if "/search" in goal_l:
            target = f"{base}/search"
        elif "/demo" in goal_l:
            target = f"{base}/demo"
        else:
            # prefer search (protected page) so we can test full flow after login if needed
            target = f"{base}/search"

        await _goto(page, target)

        # 2) If login page appears, use default admin creds (your app creates them)
        if "login" in (page.url or "") or (await page.locator('input[name="username"]').count() and await page.locator('button[type="submit"]').count()):
            try:
                await page.fill('input[name="username"]', "admin")
                await page.fill('input[name="password"]', "admin123")
                await page.click('button[type="submit"]')
                # After login, we should land on /search
                await page.wait_for_load_state("domcontentloaded")
            except Exception:
                pass  # continue anyway

        # 3) list categories if asked
        if "list categories" in goal_l or "all categories" in goal_l:
            btn = page.locator('button[name="list_all"]')
            if await btn.count():
                await btn.click()
                await page.wait_for_load_state("domcontentloaded")
            # read category chips (server renders anchors with class 'category-chip' in index.html)
            chips = page.locator(".category-list a")
            cats = [c.strip() for c in await chips.all_inner_texts()] if await chips.count() else []
            return {"status": "success", "action": "list_categories", "categories": cats}

        # 4) extract desired category from goal, e.g., "travel", "science"
        m = re.search(r"(?:category|search)\s+(?:for\s+)?['\"]?([a-zA-Z ]+)['\"]?", goal_l)
        desired = m.group(1).strip() if m else None

        if desired:
            # try the plain search bar first
            if await page.locator('input[name="query"]').count():
                await page.fill('input[name="query"]', desired)
                if await page.locator('button[type="submit"]').count():
                    await page.click('button[type="submit"]')
                    await page.wait_for_load_state("domcontentloaded")

            # If the page shows "Available categories", click the closest chip if rendered
            choices = page.locator(".category-list a")
            if await choices.count():
                # pick the first chip that fuzzy matches desired
                texts = await choices.all_inner_texts()
                pick_idx = None
                d = desired.lower()
                for idx, t in enumerate(texts):
                    if d in t.lower():
                        pick_idx = idx
                        break
                if pick_idx is None and texts:
                    pick_idx = 0  # fall back to first
                if pick_idx is not None:
                    await choices.nth(pick_idx).click()
                    await page.wait_for_load_state("domcontentloaded")

        # 5) gather first few items if present
        if await page.locator(".product_pod").count():
            titles = await page.locator(".product_pod h3 a").all_inner_texts()
            prices = await page.locator(".price_color").all_inner_texts()
            items = [{"title": t.strip(), "price": p.strip()} for t, p in zip(titles, prices)]
            return {"status": "success", "action": "collect_items", "count": len(items), "items": items[:5]}

        # Nothing matched
        return {"status": "noop", "message": "No items found or goal too vague.", "url": page.url}


# ---------------------- Public API ----------------------

def run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """
    Entry point called by Flask /mcp/run.
    - planner='builtin' runs a fast, single-session executor (recommended)
    - in future you could wire other planners that emit steps
    """
    async def _run():
        if planner == "builtin":
            return await _builtin_executor(goal, headless=headless)
        # Fallback: still do builtin to keep UX snappy
        return await _builtin_executor(goal, headless=headless)

    return asyncio.run(_run())
