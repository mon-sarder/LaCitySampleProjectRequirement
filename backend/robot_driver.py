# robot_driver.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

def search_product(product_name: str):
    """Search for a product on Books to Scrape and return the title and price."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Navigate to the site
            page.goto("https://books.toscrape.com", timeout=15000)

            # Example: just open a fixed category or find title in list
            page.click("a[href*='music_14']", timeout=10000)
            page.wait_for_selector(".product_pod", timeout=10000)

            # Click first result
            first_book = page.locator(".product_pod").first
            first_book.click()
            page.wait_for_selector(".product_main h1", timeout=10000)

            title = page.text_content(".product_main h1")
            price = page.text_content(".price_color")

            browser.close()

            return {"status": "success", "title": title, "price": price}

    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Page load timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

