# mcp_agent.py
"""
MCP AI Goal Executor — Intelligent Router
-----------------------------------------
Executes natural-language goals by automatically selecting
the correct automation driver (search, login, or browse).

All Playwright sessions use the shared custom User-Agent:
    BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)
"""

import asyncio
from playwright.async_api import async_playwright
from robot_driver import search_product
from login_driver import run_login_test

CUSTOM_UA = "BroncoBot/1.0 (+https://github.com/mon-sarder/BroncoFit)"


async def _simple_scrape(goal: str, agent: str, headless: bool = True):
    """Default fallback: open BooksToScrape and read category."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=CUSTOM_UA)
        page = await context.new_page()
        await page.goto("https://books.toscrape.com/")
        await page.wait_for_selector(".product_pod")
        title = await page.locator(".product_pod h3 a").nth(0).inner_text()
        price = await page.locator(".price_color").nth(0).inner_text()
        await browser.close()
        return {
            "status": "success",
            "goal": goal,
            "title": title,
            "price": price,
            "meta": "Simple scrape completed.",
            "agent": agent
        }


async def _run_ai_goal_async(goal: str,
                             planner: str = "builtin",
                             headless: bool = True,
                             agent: str = "BroncoMCP/1.0"):
    """
    Interprets the goal and routes execution:
      - If goal includes “login”, use login_driver
      - If goal includes “search”, use robot_driver
      - Otherwise, do a simple autonomous scrape
    """
    print(f"[{agent}] Executing MCP AI goal: '{goal}' via {planner}")

    goal_lower = goal.lower()

    # 1. Handle login tasks
    if "login" in goal_lower:
        # extract basic credentials if given
        username = "student"
        password = "Password123"
        if "admin" in goal_lower:
            username = "admin"
            password = "admin123"
        print(f"[{agent}] Routing goal to login_driver for {username}")
        result = run_login_test(username=username, password=password, agent=agent)
        result["goal"] = goal
        result["planner"] = planner
        return result

    # 2. Handle product/category search tasks
    elif any(k in goal_lower for k in ["search", "find", "category", "book", "browse"]):
        import re
        # try to extract a simple keyword after "search"
        match = re.search(r"search for ([\w\s]+)", goal_lower)
        keyword = match.group(1).strip() if match else "travel"
        print(f"[{agent}] Routing goal to robot_driver for query '{keyword}'")
        data = search_product(keyword, agent=agent)
        data["goal"] = goal
        data["planner"] = planner
        return data

    # 3. Default: simple scraping
    else:
        print(f"[{agent}] Running simple fallback scrape.")
        return await _simple_scrape(goal, agent, headless=headless)


def run_ai_goal(goal: str,
                planner: str = "builtin",
                headless: bool = True,
                agent: str = "BroncoMCP/1.0"):
    """
    Public synchronous entrypoint for app.py
    """
    return asyncio.run(_run_ai_goal_async(goal, planner, headless, agent))
