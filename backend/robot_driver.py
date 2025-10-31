# robot_driver.py
import asyncio
from playwright.async_api import async_playwright

CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"

async def _search_async(query: str, agent: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=CUSTOM_UA)
        page = await context.new_page()

        await page.goto("https://books.toscrape.com/")
        await page.wait_for_load_state("domcontentloaded")

        # Grab all categories
        cats = await page.locator(".side_categories a").all_inner_texts()
        cats = [c.strip() for c in cats if c.strip() and c.lower() != "books"]

        # Try to find closest match
        match = None
        for c in cats:
            if query.lower() in c.lower():
                match = c
                break

        # If no close match, return choices
        if not match:
            await browser.close()
            return {
                "status": "choices",
                "categories": cats,
                "message": f"No exact match for '{query}'. Choose one of these categories.",
                "agent": agent
            }

        # Otherwise, open that category
        await page.click(f"text={match}")
        await page.wait_for_selector(".product_pod")

        titles = await page.locator(".product_pod h3 a").all_inner_texts()
        prices = await page.locator(".price_color").all_inner_texts()

        items = [{"title": t.strip(), "price": p.strip()} for t, p in zip(titles, prices)]
        await browser.close()

        return {
            "status": "success",
            "category": match,
            "items": items,
            "meta": f"{len(items)} items found",
            "agent": agent
        }

def search_product(query: str, agent="BroncoMCP/1.0"):
    print(f"[{agent}] Searching for '{query}' ...")
    return asyncio.run(_search_async(query, agent))
