# login_driver.py
import asyncio
from playwright.async_api import async_playwright

CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"

async def _login_async(username, password, agent):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=CUSTOM_UA)
        page = await context.new_page()

        # Example: dummy login test site
        await page.goto("https://www.saucedemo.com/")
        await page.fill("#user-name", username)
        await page.fill("#password", password)
        await page.click("#login-button")
        await page.wait_for_load_state("networkidle")

        text = await page.inner_text("body")
        status = "success" if "Products" in text else "error"
        msg = "Login successful!" if status == "success" else "Login failed."

        await browser.close()
        return {"status": status, "message": msg, "agent": agent}

def run_login_test(username, password, agent="BroncoMCP/1.0"):
    print(f"[{agent}] Running login test for user '{username}' ...")
    return asyncio.run(_login_async(username, password, agent))
