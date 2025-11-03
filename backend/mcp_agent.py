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
import traceback
from contextlib import asynccontextmanager
from typing import Dict, Any

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

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

    # Special case: health check requests
    if "health" in goal_l and ("check" in goal_l or "api" in goal_l or "/api/health" in goal_l):
        return {
            "status": "noop",
            "message": "Health checks should use the dedicated /api/health endpoint or check_health MCP tool",
            "url": "http://localhost:5001/api/health"
        }

    try:
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

            try:
                await _goto(page, target)
            except PWTimeoutError:
                return {
                    "status": "error",
                    "message": f"Timeout navigating to {target}",
                    "url": target
                }

            # 2) If login page appears, use default admin creds (your app creates them)
            try:
                if "login" in (page.url or "").lower():
                    username_input = page.locator('input[name="username"]')
                    password_input = page.locator('input[name="password"]')
                    submit_btn = page.locator('button[type="submit"]')

                    if await username_input.count() and await password_input.count() and await submit_btn.count():
                        await username_input.fill("admin")
                        await password_input.fill("admin123")
                        await submit_btn.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception as e:
                # Continue anyway - might already be logged in
                pass

            # 3) list categories if asked
            if "list" in goal_l and "categor" in goal_l:
                btn = page.locator('button:has-text("Show categories"), button[name="list_all"]')
                try:
                    if await btn.count():
                        await btn.first.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass

                # Read category chips/buttons
                chips = page.locator(".category-list a, .chips .chip, .category-chip")
                try:
                    if await chips.count():
                        cats = []
                        count = await chips.count()
                        for i in range(min(count, 100)):  # Limit to prevent hanging
                            text = await chips.nth(i).inner_text()
                            cats.append(text.strip())
                        return {
                            "status": "success",
                            "action": "list_categories",
                            "categories": cats,
                            "count": len(cats)
                        }
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to read categories: {str(e)}",
                        "categories": []
                    }

            # 4) extract desired category from goal, e.g., "travel", "science"
            m = re.search(r"(?:category|search|find|show)\s+(?:for\s+)?['\"]?([a-zA-Z ]+)['\"]?", goal_l)
            desired = m.group(1).strip() if m else None

            if desired:
                # Try the plain search bar first
                query_input = page.locator('input[name="query"]')
                if await query_input.count():
                    try:
                        await query_input.fill(desired)
                        submit = page.locator('button[type="submit"]')
                        if await submit.count():
                            await submit.first.click()
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass

                # If the page shows "Available categories", click the closest chip if rendered
                choices = page.locator(".category-list a, .chips .chip")
                if await choices.count():
                    try:
                        # Pick the first chip that fuzzy matches desired
                        texts = []
                        count = await choices.count()
                        for i in range(min(count, 100)):
                            t = await choices.nth(i).inner_text()
                            texts.append(t)

                        pick_idx = None
                        d = desired.lower()
                        for idx, t in enumerate(texts):
                            if d in t.lower():
                                pick_idx = idx
                                break
                        if pick_idx is None and texts:
                            pick_idx = 0  # Fall back to first

                        if pick_idx is not None:
                            await choices.nth(pick_idx).click()
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass

            # 5) Gather first few items if present (Books to Scrape format)
            pods = page.locator(".product_pod, article.product_pod")
            if await pods.count():
                try:
                    items = []
                    count = await pods.count()
                    for i in range(min(count, 10)):  # Limit to first 10
                        pod = pods.nth(i)
                        title_elem = pod.locator("h3 a, .product_pod h3 a")
                        price_elem = pod.locator(".price_color")

                        if await title_elem.count() and await price_elem.count():
                            title = await title_elem.first.get_attribute("title")
                            if not title:
                                title = await title_elem.first.inner_text()
                            price = await price_elem.first.inner_text()
                            items.append({
                                "title": title.strip(),
                                "price": price.strip()
                            })

                    if items:
                        return {
                            "status": "success",
                            "action": "collect_items",
                            "count": len(items),
                            "items": items,
                            "url": page.url
                        }
                except Exception as e:
                    pass

            # Nothing matched or found
            return {
                "status": "noop",
                "message": "No items found or goal too vague.",
                "url": page.url
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Executor error: {str(e)}",
            "traceback": traceback.format_exc()
        }


# ---------------------- Public API ----------------------

def run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """
    Entry point called by Flask /api/run.
    - planner='builtin' runs a fast, single-session executor (recommended)
    - in future you could wire other planners that emit steps
    """

    async def _run():
        if planner == "builtin":
            return await _builtin_executor(goal, headless=headless)
        # Fallback: still do builtin to keep UX snappy
        return await _builtin_executor(goal, headless=headless)

    try:
        return asyncio.run(_run())
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to run goal: {str(e)}",
            "traceback": traceback.format_exc()
        }