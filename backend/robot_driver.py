# robot_driver.py
"""
Fast Playwright helpers for the Required Core demo.
- Headless Chromium
- Tight timeouts (3s / 5s)
- domcontentloaded waits
- Minimal scraping

Public API:
  - search_product(query: str, agent="BroncoMCP/1.0", headless=True) -> dict
  - list_categories(agent="BroncoMCP/1.0", headless=True) -> dict
"""

import asyncio
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright

# ---------- Speed / runtime knobs ----------
DEFAULT_TIMEOUT_MS = 3000          # element waits
DEFAULT_NAV_TIMEOUT_MS = 5000      # navigation waits
HEADLESS_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
]

# Shared UA with mcp_agent.py
CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"


@asynccontextmanager
async def _browser_ctx(headless: bool = True):
    """Fast chromium context with tight timeouts."""
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


async def _collect_categories(page):
    """Return all non-empty category names except root 'Books'."""
    cats = await page.locator(".side_categories a").all_inner_texts()
    cats = [c.strip() for c in cats if c.strip()]
    return [c for c in cats if c.lower() != "books"]


async def _search_async(query: str, agent: str, headless: bool = True):
    query = (query or "").strip()

    async with _browser_ctx(headless=headless) as (_b, _c, page):
        await _goto(page, "https://books.toscrape.com/")
        cats = await _collect_categories(page)

        # List-all path (empty query or explicit "show categories" flow)
        if not query:
            return {
                "status": "choices",
                "categories": cats,
                "message": "Available categories:",
                "agent": agent,
            }

        # Try contains-match first
        qlower = query.lower()
        match = next((c for c in cats if qlower in c.lower()), None)

        if not match:
            return {
                "status": "choices",
                "categories": cats,
                "message": f"No close category match for '{query}'. Pick one of the available categories.",
                "agent": agent,
            }

        # Open matched category (fast waits)
        await page.click(f"text={match}")
        await page.locator(".product_pod").first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

        # Grab first page items only (fast)
        titles = await page.locator(".product_pod h3 a").all_inner_texts()
        prices = await page.locator(".price_color").all_inner_texts()
        items = [{"title": t.strip(), "price": p.strip()} for t, p in zip(titles, prices)]

        return {
            "status": "success",
            "category": match,
            "items": items,
            "meta": f"{len(items)} items found",
            "agent": agent,
        }


def search_product(query: str, agent="BroncoMCP/1.0", headless: bool = True):
    """
    Synchronous wrapper for Flask.
      - Empty query => list categories
      - Partial match => open category and list items
      - Otherwise => return suggestions
    """
    return asyncio.run(_search_async(query, agent, headless=headless))


def list_categories(agent="BroncoMCP/1.0", headless: bool = True):
    async def _list():
        async with _browser_ctx(headless=headless) as (_b, _c, page):
            await _goto(page, "https://books.toscrape.com/")
            cats = await _collect_categories(page)
            return {"status": "choices", "categories": cats, "message": "Available categories:", "agent": agent}

    return asyncio.run(_list())
