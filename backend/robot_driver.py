# robot_driver.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os, difflib

DEFAULT_TIMEOUT = 20_000  # ms
HOME_URL = "http://books.toscrape.com/"

def _normalize(s: str) -> str:
    return (s or "").strip().lower()

def _collect_categories(page):
    """
    Returns a list of category names (excluding the top 'Books' root).
    """
    page.goto(HOME_URL, timeout=DEFAULT_TIMEOUT)
    page.wait_for_load_state("domcontentloaded")
    # Sidebar categories (anchor text). First link is root "Books", skip it.
    links = page.locator(".side_categories a").all()
    names = []
    for a in links:
        txt = (a.text_content() or "").strip()
        if txt and txt.lower() != "books":
            names.append(txt)
    # De-dup & keep order
    seen = set(); ordered = []
    for n in names:
        if n not in seen:
            ordered.append(n); seen.add(n)
    return ordered

def _fuzzy_pick(target: str, choices):
    """
    Try exact, then substring, then difflib fuzzy match.
    Returns (match_or_None, used_strategy)
    """
    t = _normalize(target)
    norm_map = {c: _normalize(c) for c in choices}

    # Exact (case-insensitive)
    for c, n in norm_map.items():
        if n == t:
            return c, "exact"

    # Substring (e.g., 'food' -> 'Food and Drink')
    for c, n in norm_map.items():
        if t and t in n:
            return c, "substring"

    # Fuzzy (closest match)
    best = difflib.get_close_matches(t, list(norm_map.values()), n=1, cutoff=0.72)
    if best:
        best_norm = best[0]
        # find original case spelling
        for c, n in norm_map.items():
            if n == best_norm:
                return c, "fuzzy"

    return None, None

def search_product(product_name: str = "music"):
    """
    Navigate to Books to Scrape, pick a category (fuzzy), open the first book,
    and return title+price. If no near match, return the full category list
    so the UI can render clickable choices.
    """
    headless = os.environ.get("HEADFUL") not in ("1", "true", "True")
    desired = (product_name or "").strip()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()

            categories = _collect_categories(page)

            # Decide the category
            picked, how = _fuzzy_pick(desired, categories) if desired else (None, None)

            if not picked:
                # No close match → let the UI present choices
                browser.close()
                return {
                    "status": "choices",
                    "message": "No close category match. Pick one of the available categories.",
                    "categories": categories
                }

            # Click the chosen category by accessible name
            page.get_by_role("link", name=picked).click(timeout=DEFAULT_TIMEOUT)

            # Open first product
            page.wait_for_selector(".product_pod", timeout=DEFAULT_TIMEOUT)
            page.locator(".product_pod a").first.click()
            page.wait_for_selector(".product_main h1", timeout=DEFAULT_TIMEOUT)

            title = (page.text_content(".product_main h1") or "").strip()
            price = (page.text_content(".price_color") or "").strip()

            page.close()
            browser.close()

            meta = f"Category: {picked} (match: {how})"
            return {"status": "success", "title": title, "price": price, "meta": meta}

    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Page load timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
