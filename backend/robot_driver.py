# robot_driver.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os, difflib

DEFAULT_TIMEOUT = 20_000  # ms
HOME_URL = "http://books.toscrape.com/"

def _normalize(s: str) -> str:
    return (s or "").strip().lower()

def _collect_categories(page):
    """
    Returns a list of category names (excluding the top 'Books').
    """
    page.goto(HOME_URL, timeout=DEFAULT_TIMEOUT)
    page.wait_for_load_state("domcontentloaded")
    links = page.locator(".side_categories a").all()
    names = []
    for a in links:
        txt = (a.text_content() or "").strip()
        if txt and txt.lower() != "books":
            names.append(txt)
    # de-dup while preserving order
    seen = set(); out = []
    for n in names:
        if n not in seen:
            out.append(n); seen.add(n)
    return out

def _fuzzy_pick(target: str, choices):
    """
    exact (case-insensitive) -> substring -> fuzzy (difflib)
    """
    t = _normalize(target)
    norm_map = {c: _normalize(c) for c in choices}

    for c, n in norm_map.items():
        if n == t:
            return c, "exact"
    for c, n in norm_map.items():
        if t and t in n:
            return c, "substring"
    best = difflib.get_close_matches(t, list(norm_map.values()), n=1, cutoff=0.72)
    if best:
        best_norm = best[0]
        for c, n in norm_map.items():
            if n == best_norm:
                return c, "fuzzy"
    return None, None

def _collect_items_on_category(page, limit=20):
    """
    On a category page, collect up to `limit` items (title + price) on the first page.
    """
    page.wait_for_selector(".product_pod", timeout=DEFAULT_TIMEOUT)
    pods = page.locator(".product_pod")
    count = min(pods.count(), limit)
    items = []
    for i in range(count):
        pod = pods.nth(i)
        # title is in the anchor title attribute inside h3
        title = (pod.locator("h3 a").get_attribute("title") or "").strip()
        if not title:
            title = (pod.locator("h3").text_content() or "").strip()
        price = (pod.locator(".price_color").text_content() or "").strip()
        items.append({"title": title, "price": price})
    return items

def search_product(product_name: str = "music"):
    """
    If no near match to a category is found -> return {"status":"choices","categories":[...]}.
    If a category is decided -> return {"status":"success","category":..., "items":[{title,price}...]}.
    """
    headless = os.environ.get("HEADFUL") not in ("1", "true", "True")
    desired = (product_name or "").strip()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()

            categories = _collect_categories(page)
            picked, how = _fuzzy_pick(desired, categories) if desired else (None, None)

            if not picked:
                browser.close()
                return {
                    "status": "choices",
                    "message": "No close category match. Pick one of the available categories.",
                    "categories": categories
                }

            # click the category and collect items
            page.get_by_role("link", name=picked).click(timeout=DEFAULT_TIMEOUT)
            items = _collect_items_on_category(page, limit=20)

            page.close()
            browser.close()

            return {
                "status": "success",
                "category": picked,
                "items": items,
                "meta": f"Category: {picked} (match: {how}), items on first page: {len(items)}"
            }

    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Page load timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
