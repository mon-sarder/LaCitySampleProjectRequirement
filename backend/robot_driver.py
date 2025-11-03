# robot_driver.py
# Robust Playwright scraper for "Books to Scrape"
# - Defensive against layout/timeout issues
# - Always returns a stable JSON shape for the API
# - Fuzzy matches category; returns categories when no match
#
# Public functions:
#   - search_product(category: str, limit: int | None = None) -> dict
#   - list_categories() -> list[dict]  (name, url)

from __future__ import annotations

import os
import re
import difflib
from typing import List, Dict, Any, Tuple, Optional

from playwright.sync_api import sync_playwright


BOOKS_BASE = "http://books.toscrape.com/"
AGENT_NAME = "BroncoMCP/1.0"

# --- Speed & behavior tuners (override via env) -------------------------------
HEADLESS = os.environ.get("PW_HEADLESS", "1").lower() in ("1", "true", "yes")
NAV_TIMEOUT_MS = int(os.environ.get("PW_NAV_TIMEOUT_MS", "15000"))
SLOWMO_MS = int(os.environ.get("PW_SLOWMO_MS", "0"))
CUSTOM_UA = os.environ.get(
    "CUSTOM_UA",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# -----------------------------------------------------------------------------


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _launch_browser():
    """Launch Chromium with hardened defaults."""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO_MS)
    context = browser.new_context(user_agent=CUSTOM_UA, viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)
    return pw, browser, context, page


def _extract_categories(page) -> List[Dict[str, str]]:
    """
    Returns a list of categories from the home page:
    [{"name": "Travel", "url": "http://.../category/books/travel_2/index.html"}, ...]
    """
    page.goto(BOOKS_BASE)
    cats: List[Dict[str, str]] = []
    # Categories live under the left sidebar list:
    # ul.nav-list > li > ul > li > a
    anchors = page.locator("ul.nav-list ul li a")
    count = anchors.count()
    for i in range(count):
        a = anchors.nth(i)
        name = _normalize(a.inner_text())
        href = a.get_attribute("href") or ""
        if not href.startswith("http"):
            href = BOOKS_BASE + href.lstrip("/")
        # Re-titleize the name for display
        title = name.title()
        cats.append({"name": title, "url": href})
    return cats


def _best_category_url(categories: List[Dict[str, str]], query: str) -> Optional[str]:
    """Pick the closest category URL by fuzzy matching on name."""
    if not categories:
        return None
    q = _normalize(query)
    names = [c["name"] for c in categories]  # already title-ized
    # make a map from lower -> original
    low_to_cat = {c["name"].lower(): c for c in categories}
    # difflib returns a list of best textual matches
    best = difflib.get_close_matches(q, [n.lower() for n in names], n=1, cutoff=0.6)
    if not best:
        return None
    return low_to_cat[best[0]]["url"]


def _scrape_category_items(page, cat_url: str, limit: int | None = None) -> List[Dict[str, Any]]:
    """
    Scrape a category page for product pods (title + price).
    """
    page.goto(cat_url)

    # Items are in 'ol.row li article.product_pod'
    pods = page.locator("ol.row li article.product_pod")
    count = pods.count()
    items: List[Dict[str, Any]] = []
    for i in range(count):
        art = pods.nth(i)
        # Title is in h3 > a[title], fallback to text
        title_attr = art.locator("h3 a").get_attribute("title") or ""
        if not title_attr:
            title_attr = art.locator("h3 a").inner_text()
        title = title_attr.strip()

        price_txt = (art.locator(".price_color").inner_text() or "").strip()
        # e.g. "£45.17" – keep as text (UI formats)
        items.append({"title": title, "price": price_txt})

        if limit and len(items) >= limit:
            break
    return items


def list_categories() -> List[Dict[str, str]]:
    """Convenience function to fetch categories (used by /categories.json and MCP)."""
    pw, browser, context, page = _launch_browser()
    try:
        cats = _extract_categories(page)
        return cats
    finally:
        try:
            context.close()
            browser.close()
            pw.stop()
        except Exception:
            pass


def search_product(category: str, limit: int | None = None, headless: Optional[bool] = None) -> Dict[str, Any]:
    """
    Main entrypoint used by Flask /search-json and MCP.

    Returns dict:
    {
      "agent": "BroncoMCP/1.0",
      "status": "success" | "no_match" | "error",
      "category": "<normalized-requested>",
      "items": [ {title, price}, ... ],
      "meta": { "categories": [ {name,url},... ] }
    }
    """
    requested = (category or "").strip()
    normalized = requested or ""

    # Optional override for headless at call time
    if headless is not None:
        # override module-level HEADLESS just for this call
        os.environ["PW_HEADLESS"] = "1" if headless else "0"

    pw, browser, context, page = _launch_browser()
    try:
        # 1) Gather categories up front (so we can return them on no-match)
        cats = _extract_categories(page)

        # 2) Find best category
        best_url = _best_category_url(cats, normalized)
        if not normalized or normalized.lower() in ("*", "all", "everything"):
            # treat as "list everything" request: send back categories only
            return {
                "agent": AGENT_NAME,
                "status": "no_match",
                "category": normalized,
                "items": [],
                "meta": {"categories": cats}
            }

        if not best_url:
            # No close match – tell UI to show categories to click
            return {
                "agent": AGENT_NAME,
                "status": "no_match",
                "category": normalized,
                "items": [],
                "meta": {"categories": cats}
            }

        # 3) Scrape items for that category
        items = _scrape_category_items(page, best_url, limit=limit)

        # Defensive: force list
        if isinstance(items, dict):
            items = [items]
        elif not isinstance(items, list):
            items = []

        return {
            "agent": AGENT_NAME,
            "status": "success",
            "category": normalized,
            "items": items,
            "meta": {
                "categories": cats,
                "category_url": best_url,
                "count": len(items)
            }
        }

    except Exception as e:
        # Fail safe: return a well-formed error body (items = [])
        return {
            "agent": AGENT_NAME,
            "status": "error",
            "category": normalized,
            "message": str(e),
            "items": [],
            "meta": {"note": "scraper failure; returned empty list"}
        }
    finally:
        try:
            context.close()
            browser.close()
            pw.stop()
        except Exception:
            pass


# If you want a quick local test:
if __name__ == "__main__":
    # Example: python robot_driver.py
    from pprint import pprint

    print("== Categories ==")
    try:
        pprint(list_categories()[:10])
    except Exception as e:
        print("Categories error:", e)

    print("\n== Search: 'travel' (top 5) ==")
    res = search_product("travel", limit=5)
    pprint(res)
