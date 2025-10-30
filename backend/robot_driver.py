from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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
    try:
        # normalize input
        key = (product_name or "").strip().lower()
        category = CATEGORY_NAMES.get(key, "Music")
        used_default = category == "Music" and key not in ("music", "")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # NOTE: site is HTTP, not HTTPS
            page.goto("http://books.toscrape.com/", timeout=20000)
            page.wait_for_load_state("domcontentloaded")

            # click the chosen category by accessible name
            page.get_by_role("link", name=category).click(timeout=15000)

            page.wait_for_selector(".product_pod", timeout=15000)
            page.locator(".product_pod a").first.click()
            page.wait_for_selector(".product_main h1", timeout=15000)

            title = (page.text_content(".product_main h1") or "").strip()
            price = (page.text_content(".price_color") or "").strip()
            browser.close()

            meta = f"Category: {category}"
            if used_default:
                meta += " (input not recognized → defaulted to Music)"
            return {"status": "success", "title": title, "price": price, "meta": meta}

    except TimeoutError:
        return {"status": "error", "message": "Page load timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
