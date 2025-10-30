# login_driver.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Mirror this value if you want the constant in one place (but app.py is authoritative):
MAX_CRED_LENGTH = 50

def run_login_test(username: str = "student", password: str = "Password123"):
    """
    Demo login automation against a public practice page.
    Accepts username/password (already validated by the server).
    """
    # Defensive server-side check: refuse if too long
    if len(username) > MAX_CRED_LENGTH or len(password) > MAX_CRED_LENGTH:
        return {
            "status": "error",
            "message": f"Possible buffer overflow attempt: credential length exceeds {MAX_CRED_LENGTH}."
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Demo login page with test creds
            page.goto("https://practicetestautomation.com/practice-test-login/", timeout=20000)
            page.wait_for_selector("#username", timeout=15000)

            # Fill and submit using provided values (already validated/trimmed)
            page.fill("#username", username)
            page.fill("#password", password)
            page.click("#submit")

            # Wait for success indicator
            page.wait_for_selector(".post-title", timeout=15000)
            success_text = (page.text_content(".post-title") or "").strip()

            page.close()
            browser.close()
            return {"status": "success", "message": success_text}

    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Login failed: timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
