# robot_driver.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os

DEFAULT_TIMEOUT = 20_000  # ms

# Map user input -> category display name on Books to Scrape (accessible name)
CATEGORY_NAMES = {
    "music": "Music",
    "food": "Food and Drink",
    "food and drink": "Food and Drink",
    "travel": "Travel",
    "poetry": "Poetry",
    "mystery": "Mystery",
    "historical": "Historical Fiction",
    "fiction": "Fiction",
}


def search_product(product_name: str = "music"):
    """
    Open Books to Scrape (HTTP), navigate to chosen category, open the first book,
    and return its title + price + meta. Robust timeouts + selectors.
    """
    key = (product_name or "").strip().lower()
    category = CATEGORY_NAMES.get(key, "Music")
    used_default = category == "Music" and key not in ("music", "")

    headless = os.environ.get("HEADFUL") not in ("1", "true", "True")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()

            # NOTE: site is HTTP, not HTTPS
            page.goto("http://books.toscrape.com/", timeout=DEFAULT_TIMEOUT)
            page.wait_for_load_state("domcontentloaded")

            # Click category by accessible name (stable)
            page.get_by_role("link", name=category).click(timeout=DEFAULT_TIMEOUT)

            # Open first product
            page.wait_for_selector(".product_pod", timeout=DEFAULT_TIMEOUT)
            page.locator(".product_pod a").first.click()
            page.wait_for_selector(".product_main h1", timeout=DEFAULT_TIMEOUT)

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
