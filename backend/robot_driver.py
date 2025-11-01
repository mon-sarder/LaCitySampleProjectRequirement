# robot_driver.py
import asyncio
from playwright.async_api import async_playwright

CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"

async def _collect_categories(page):
    # Returns all non-empty category names (excluding the root "Books")
    cats = await page.locator(".side_categories a").all_inner_texts()
    cats = [c.strip() for c in cats if c.strip()]
    cats = [c for c in cats if c.lower() != "books"]
    return cats

async def _open_site(headless=True):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(user_agent=CUSTOM_UA)
            page = await context.new_page()
            try:
                await page.goto("https://books.toscrape.com/")
                await page.wait_for_load_state("domcontentloaded")
                yield browser, context, page
            finally:
                await browser.close()
    return _ctx()

async def _search_async(query: str, agent: str, headless: bool = True):
    # Normalize query
    query = (query or "").strip()

    async with (await _open_site(headless=headless)) as (browser, context, page):
        cats = await _collect_categories(page)

        # If query is empty, explicitly return ALL categories (the "list all" case)
        if not query:
            return {
                "status": "choices",
                "categories": cats,
                "message": "Available categories:",
                "agent": agent
            }

        # Try a case-insensitive contains match first
        match = None
        qlower = query.lower()
        for c in cats:
            if qlower in c.lower():
                match = c
                break

        # If no close match, offer choices
        if not match:
            return {
                "status": "choices",
                "categories": cats,
                "message": f"No close category match for '{query}'. Pick one of the available categories.",
                "agent": agent
            }

        # Open the matched category and collect items
        await page.click(f"text={match}")
        await page.wait_for_selector(".product_pod")

        titles = await page.locator(".product_pod h3 a").all_inner_texts()
        prices = await page.locator(".price_color").all_inner_texts()
        items = [{"title": t.strip(), "price": p.strip()} for t, p in zip(titles, prices)]

        return {
            "status": "success",
            "category": match,
            "items": items,
            "meta": f"{len(items)} items found",
            "agent": agent
        }

def search_product(query: str, agent="BroncoMCP/1.0", headless: bool = True):
    """
    Main entry point used by Flask.
    - If query is empty/blank => returns all categories (status="choices")
    - If query partially matches a category => returns items (status="success")
    - Otherwise => returns choices for user to pick
    """
    print(f"[{agent}] search_product query='{query}'")
    return asyncio.run(_search_async(query, agent, headless=headless))

# Optional helper if you want to list categories directly elsewhere
def list_categories(agent="BroncoMCP/1.0", headless: bool = True):
    async def _list():
        async with (await _open_site(headless=headless)) as (_b, _c, page):
            cats = await _collect_categories(page)
            return {"status": "choices", "categories": cats, "message": "Available categories:", "agent": agent}
    return asyncio.run(_list())
