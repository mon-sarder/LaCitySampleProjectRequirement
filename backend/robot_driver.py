# robot_driver.py
"""
Robot driver for Books to Scrape.

Stable response contract for search_product():
{
  "agent": "BroncoMCP/1.0",
  "status": "success" | "error",
  "category": "<resolved category name>",
  "items": [ {"title": "...", "price": "£..."} ],
  "meta": {
      "count": <int>,
      "category_url": "<url or null>",
      "categories": ["Travel","Mystery",...],   # included when user’s query didn’t closely match a category
      "note": "<optional string>"               # optional diagnostic info
  }
}

Behavior:
- Fuzzy-matches the user query against site categories.
- If no close match, returns ALL categories in meta.categories and an empty items list.
- Paginates a category to collect items (respects optional 'limit').
- Always returns items as a list (even if only one item).
"""

from __future__ import annotations

import re
import time
from typing import List, Dict, Optional, Tuple
from difflib import get_close_matches

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

BOOKS_ROOT = "https://books.toscrape.com/"
AGENT_NAME = "BroncoMCP/1.0"

# Tunables
NAV_TIMEOUT_MS = 15000
REQ_TIMEOUT_MS = 15000
PAGINATION_MAX_PAGES = 50  # hard safety cap


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _abs_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("./"):
        href = href[2:]
    return BOOKS_ROOT + href


def _get_categories(page) -> List[Tuple[str, str]]:
    """
    Returns list of (category_name, category_url).
    """
    categories: List[Tuple[str, str]] = []
    # Sidebar list
    for a in page.locator(".nav-list ul li a").all():
        name = _clean_text(a.inner_text())
        href = a.get_attribute("href") or ""
        if not name:
            continue
        categories.append((name, _abs_url(href)))
    return categories


def _closest_category(query: str, categories: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    names = [name for name, _ in categories]
    if not query:
        return None
    matches = get_close_matches(query.lower(), [n.lower() for n in names], n=1, cutoff=0.65)
    if not matches:
        return None
    target_lower = matches[0]
    for (name, url) in categories:
        if name.lower() == target_lower:
            return (name, url)
    return None


def _extract_items_from_category(page, limit: Optional[int]) -> List[Dict[str, str]]:
    """
    Iterates all pages of a category; collects book title and price.
    Respects 'limit' if provided.
    """
    items: List[Dict[str, str]] = []

    def scrape_current_page():
        cards = page.locator(".product_pod")
        count = cards.count()
        for i in range(count):
            card = cards.nth(i)
            title = _clean_text(card.locator("h3 a").get_attribute("title") or "")
            price = _clean_text(card.locator(".price_color").inner_text())
            if title:
                items.append({"title": title, "price": price})
            if limit is not None and len(items) >= limit:
                return True
        return False

    # First page
    if scrape_current_page():
        return items

    # Pagination
    pages_seen = 1
    while pages_seen < PAGINATION_MAX_PAGES:
        next_link = page.locator("li.next a")
        if next_link.count() == 0:
            break
        next_href = next_link.get_attribute("href") or ""
        if not next_href:
            break
        # Click/Go to next page
        try:
            next_link.click(timeout=REQ_TIMEOUT_MS)
            page.wait_for_selector(".product_pod", timeout=REQ_TIMEOUT_MS)
        except PWTimeoutError:
            break

        pages_seen += 1
        if scrape_current_page():
            break

    return items


def search_product(product: str, limit: Optional[int] = None) -> Dict:
    """
    High-level search entry:
      - Resolve the category from 'product' (fuzzy).
      - If no close match, return meta.categories and no items.
      - Else, scrape that category and return items.

    Returns the canonical response dict described at the top of the file.
    """
    query = (product or "").strip()
    if limit is not None:
        try:
            limit = int(limit)
            if limit <= 0:
                limit = None
        except Exception:
            limit = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(user_agent="Mozilla/5.0 BroncoMCP")
        page = context.new_page()

        # Defensive navigation to root
        try:
            page.goto(BOOKS_ROOT, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        except PWTimeoutError:
            browser.close()
            return {
                "agent": AGENT_NAME,
                "status": "error",
                "category": query,
                "items": [],
                "meta": {"note": "Timeout navigating to site root"}
            }

        # Grab categories
        try:
            page.wait_for_selector(".nav-list ul li a", timeout=REQ_TIMEOUT_MS)
            categories = _get_categories(page)
        except PWTimeoutError:
            browser.close()
            return {
                "agent": AGENT_NAME,
                "status": "error",
                "category": query,
                "items": [],
                "meta": {"note": "Could not load categories"}
            }

        # No or bad query -> offer the catalog so the caller can pick
        if not query:
            browser.close()
            return {
                "agent": AGENT_NAME,
                "status": "success",
                "category": "",
                "items": [],
                "meta": {
                    "categories": [name for (name, _) in categories],
                    "count": 0,
                    "category_url": None,
                    "note": "No query provided; listing categories"
                }
            }

        # Find closest category
        resolved = _closest_category(query, categories)
        if not resolved:
            browser.close()
            return {
                "agent": AGENT_NAME,
                "status": "success",
                "category": query,
                "items": [],
                "meta": {
                    "categories": [name for (name, _) in categories],
                    "count": 0,
                    "category_url": None,
                    "note": "No close category match; choose from 'categories'"
                }
            }

        resolved_name, resolved_url = resolved

        # Navigate to the category
        try:
            page.goto(resolved_url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            page.wait_for_selector(".product_pod", timeout=REQ_TIMEOUT_MS)
        except PWTimeoutError:
            browser.close()
            return {
                "agent": AGENT_NAME,
                "status": "error",
                "category": resolved_name,
                "items": [],
                "meta": {
                    "count": 0,
                    "category_url": resolved_url,
                    "note": "Timeout navigating category page"
                }
            }

        # Extract items with pagination
        items = _extract_items_from_category(page, limit=limit)
        browser.close()

        return {
            "agent": AGENT_NAME,
            "status": "success",
            "category": resolved_name,
            "items": items,
            "meta": {
                "count": len(items),
                "category_url": resolved_url
            }
        }
