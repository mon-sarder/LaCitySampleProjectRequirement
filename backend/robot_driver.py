# robot_driver.py
# Scraper utilities used by your Flask API + MCP server
# Updated to return multiple results from category pages.

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import re

BOOKS_ROOT = "https://books.toscrape.com/"
AGENT_NAME = "BroncoMCP/1.0"

def _clean(text: str) -> str:
    """Normalize whitespace and trim text safely."""
    return re.sub(r"\s+", " ", (text or "").strip())

def list_categories() -> dict:
    """
    Return all available categories from Books to Scrape.
    Shape:
    {
      "agent": "BroncoMCP/1.0",
      "status": "success",
      "categories": ["Travel", "Mystery", ...],
      "meta": {"count": 50}
    }
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(BOOKS_ROOT, timeout=12000, wait_until="domcontentloaded")
            links = page.locator(".nav-list ul li a")
            n = links.count()
            cats = [_clean(links.nth(i).inner_text()) for i in range(n)]
            return {
                "agent": AGENT_NAME,
                "status": "success",
                "categories": cats,
                "meta": {"count": len(cats)}
            }
        except PWTimeoutError:
            return {
                "agent": AGENT_NAME,
                "status": "error",
                "categories": [],
                "meta": {"note": "Timeout while fetching categories"}
            }
        finally:
            browser.close()

def _find_category_url(page, query: str) -> str | None:
    """
    Try to find a category URL by exact or near match.
    Returns absolute URL or None if not found.
    """
    links = page.locator(".nav-list ul li a")
    n = links.count()
    query_l = (query or "").strip().lower()
    if not query_l:
        return None

    # First pass: exact (case-insensitive)
    for i in range(n):
        name = _clean(links.nth(i).inner_text())
        if name.lower() == query_l:
            href = links.nth(i).get_attribute("href") or ""
            return BOOKS_ROOT + href

    # Second pass: startswith / contains
    for i in range(n):
        name = _clean(links.nth(i).inner_text())
        nl = name.lower()
        if nl.startswith(query_l) or query_l in nl:
            href = links.nth(i).get_attribute("href") or ""
            return BOOKS_ROOT + href

    return None

def search_product(product: str, limit: int = 10) -> dict:
    """
    Scrape books within a category. Returns up to `limit` items (default 10).
    Response shape (stable):
    {
      "agent": "BroncoMCP/1.0",
      "status": "success" | "no_match" | "error",
      "category": "Travel",
      "items": [{"title":"...","price":"£.."}, ...],
      "meta": {"count": 5, "available": 11, "note": "..."}
    }
    """
    category_query = (product or "").strip()
    items: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            # 1) Home
            page.goto(BOOKS_ROOT, timeout=12000, wait_until="domcontentloaded")

            # 2) Find category URL
            target_url = _find_category_url(page, category_query)

            # If not found, return categories to help the caller
            if not target_url:
                links = page.locator(".nav-list ul li a")
                n = links.count()
                cats = [_clean(links.nth(i).inner_text()) for i in range(n)]
                return {
                    "agent": AGENT_NAME,
                    "status": "no_match",
                    "category": category_query,
                    "items": [],
                    "meta": {
                        "count": 0,
                        "available": 0,
                        "categories": cats,
                        "note": "No close category match; returning available categories."
                    }
                }

            # 3) Go to category page
            page.goto(target_url, timeout=12000, wait_until="domcontentloaded")

            # 4) Collect products on the first page (supports limit)
            pods = page.locator("ol.row li article.product_pod")
            total_on_page = pods.count()

            for i in range(total_on_page):
                art = pods.nth(i)
                title = _clean(art.locator("h3 a").get_attribute("title") or "")
                price = _clean(art.locator(".price_color").inner_text())
                if title:
                    items.append({"title": title, "price": price})
                if limit and len(items) >= limit:
                    break

            return {
                "agent": AGENT_NAME,
                "status": "success",
                "category": category_query,
                "items": items,
                "meta": {
                    "count": len(items),
                    "available": total_on_page,
                    "note": f"Returned {len(items)} items (limit={limit}) from first page."
                }
            }

        except PWTimeoutError:
            return {
                "agent": AGENT_NAME,
                "status": "error",
                "category": category_query,
                "items": [],
                "meta": {"note": "Timeout during navigation or scraping"}
            }
        finally:
            browser.close()
