# login_driver.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os

DEFAULT_TIMEOUT = 20_000  # ms
MAX_CRED_LENGTH = 50


def run_login_test(username: str = "student", password: str = "Password123"):
    """
    Automate a login on a public demo site.
    Inputs are validated in app.py; we also defensively re-check here.
    """
    # Defensive guard even if someone bypasses the frontend
    if len(username) > MAX_CRED_LENGTH or len(password) > MAX_CRED_LENGTH:
        return {
            "status": "error",
            "message": (
                f"Possible buffer overflow attempt: credential length exceeds {MAX_CRED_LENGTH}."
            ),
        }

    headless = os.environ.get("HEADFUL") not in ("1", "true", "True")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()

            page.goto("https://practicetestautomation.com/practice-test-login/", timeout=DEFAULT_TIMEOUT)
            page.wait_for_selector("#username", timeout=DEFAULT_TIMEOUT)

            page.fill("#username", username)
            page.fill("#password", password)
            page.click("#submit")

            # Success indicator on that page
            page.wait_for_selector(".post-title", timeout=DEFAULT_TIMEOUT)
            success_text = (page.text_content(".post-title") or "").strip()

            page.close()
            browser.close()
            return {"status": "success", "message": success_text}

    except PlaywrightTimeoutError:
        return {"status": "error", "message": "Login failed: timeout or element not found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
