from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

def run_login_test():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Go to login page
            page.goto("https://practicetestautomation.com/practice-test-login/", timeout=20000)
            page.wait_for_selector("#username")

            # Fill login form
            page.fill("#username", "student")
            page.fill("#password", "Password123")
            page.click("#submit")

            # Wait for success indicator
            page.wait_for_selector(".post-title", timeout=10000)

            # Extract message
            success_text = page.text_content(".post-title")
            browser.close()

            return {"status": "success", "message": success_text}
    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Login failed: timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
