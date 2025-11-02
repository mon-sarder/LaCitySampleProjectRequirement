# robot_driver.py
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Reusable UA (also imported by mcp_agent)
CUSTOM_UA = (
    "BroncoMCP/1.0 (+https://github.com/mon-sarder/LaCitySampleProjectRequirement)"
)

BASE_URL = "http://books.toscrape.com/"

# Map user input -> site category display name (used by search_product)
CATEGORY_NAMES = {
    "music": "Music",
    "food": "Food and Drink",
    "food and drink": "Food and Drink",
    "travel": "Travel",
    "poetry": "Poetry",
    "mystery": "Mystery",
    "historical": "Historical Fiction",
    "historical fiction": "Historical Fiction",
    "fiction": "Fiction",
}

# Simple cache for list_categories()
_cache = {"cats": {"ts": 0.0, "data": []}}
_CACHE_TTL = 60 * 10  # 10 min


def list_categories(timeout=12) -> list[str]:
    """
    Return a stable, non-empty list of category names from Books to Scrape.
    Falls back to a small default set if parsing ever fails.
    """
    now = time.time()
    if now - _cache["cats"]["ts"] < _CACHE_TTL and _cache["cats"]["data"]:
        return _cache["cats"]["data"]

    try:
        resp = requests.get(f"{BASE_URL}index.html", headers={"User-Agent": CUSTOM_UA}, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        cats = []
        for a in soup.select(".side_categories ul li ul li a"):
            name = a.get_text(strip=True)
            if name:
                cats.append(name)
        if not cats:
            raise RuntimeError("category parse produced empty list")
        _cache["cats"] = {"ts": now, "data": cats}
        return cats
    except Exception:
        # Never let the API return an empty list → keep UX stable
        fallback = [
            "Travel", "Mystery", "Historical Fiction", "Sequential Art",
            "Classics", "Philosophy", "Romance", "Womens Fiction",
            "Fiction", "Childrens",
        ]
        _cache["cats"] = {"ts": now, "data": fallback}
        return fallback


def search_product(product_name: str = "music") -> dict:
    """
    Fixed task with input: open Books to Scrape (HTTP), navigate to the chosen
    category, open the first book, and return title + price + meta.
    This version keeps your Playwright flow and returns clear errors on timeouts.
    """
    try:
        key = (product_name or "").strip().lower()
        category = CATEGORY_NAMES.get(key, "Music")
        used_default = category == "Music" and key not in ("music", "")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=CUSTOM_UA)

            # site is HTTP, not HTTPS
            page.goto(BASE_URL, timeout=20000)
            page.wait_for_load_state("domcontentloaded")

            # Click category link by accessible name
            page.get_by_role("link", name=category).click(timeout=15000)

            # Open first product
            page.wait_for_selector(".product_pod", timeout=15000)
            page.locator(".product_pod a").first.click()
            page.wait_for_selector(".product_main h1", timeout=15000)

            title = (page.text_content(".product_main h1") or "").strip()
            price = (page.text_content(".price_color") or "").strip()

            page.close()
            browser.close()

            meta = f"Category: {category}"
            if used_default:
                meta += " (input not recognized → defaulted to Music)"

            return {"status": "success", "title": title, "price": price, "meta": meta}

    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Page load timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
