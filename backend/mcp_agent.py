# mcp_agent.py
"""
A tiny 'AI Brain' that plans in JSON and executes with Playwright.
- Planner modes:
  * "builtin": simple rule-based planner (no API key required)
  * "openai":   uses OpenAI chat completions (optional)
- Executor: validates and runs the JSON plan safely.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import os, json, time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --------------------
# Action schema
# --------------------
# Each step is:
# {
#   "action": "goto" | "click" | "type" | "wait_for" | "assert_text" | "extract_text" | "end",
#   "selector": "css or role locator (optional for goto/end)",
#   "text": "string for type/assert/extract (optional)",
#   "url": "for goto",
#   "timeout": 20000 (optional)
# }

ALLOWED_ACTIONS = {
    "goto", "click", "type", "wait_for", "assert_text", "extract_text", "end"
}
MAX_STEPS = 20
DEFAULT_TIMEOUT = 20000

@dataclass
class Plan:
    steps: List[Dict[str, Any]]

def _valid_step(step: Dict[str, Any]) -> bool:
    if not isinstance(step, dict): return False
    a = step.get("action")
    if a not in ALLOWED_ACTIONS: return False
    if a == "goto" and not step.get("url"): return False
    if a in {"click", "type", "wait_for", "assert_text", "extract_text"} and not step.get("selector"):
        return False
    return True

def validate_plan(plan: Dict[str, Any]) -> Optional[str]:
    if not isinstance(plan, dict) or "steps" not in plan: return "Plan must be an object with 'steps'."
    steps = plan["steps"]
    if not isinstance(steps, list) or not steps: return "Plan 'steps' must be a non-empty list."
    if len(steps) > MAX_STEPS: return f"Plan has too many steps (>{MAX_STEPS})."
    for i, s in enumerate(steps):
        if not _valid_step(s):
            return f"Invalid step at index {i}: {s}"
    return None

# --------------------
# MCP-style page context
# --------------------
def snapshot_page_context(page) -> Dict[str, Any]:
    """Small, structured context to feed the planner."""
    try:
        axtree = page.accessibility.snapshot()
    except Exception:
        axtree = None
    # Collect first N clickable elements
    clickable = page.locator("a, button, [role=button]").all()[:20]
    click_items = []
    for i, h in enumerate(clickable):
        try:
            role = h.get_attribute("role") or ""
            name = h.inner_text(timeout=500).strip()[:120]
            sel  = "xpath=" + h.evaluate("el => window.__pwpath = (el) => { const p=[]; for(;el; el=el.parentElement){ let i=0; let s=el.tagName.toLowerCase(); if(!el.parentElement){ p.unshift(s); break; } for(const sib of el.parentElement.children){ if(sib===el) break; if(sib.tagName===el.tagName) i++; } p.unshift(`${s}:nth-of-type(${i+1})`); } return p.join(' > ')}; __pwpath(this)")
        except Exception:
            role, name, sel = "", "", ""
        click_items.append({"index": i, "role": role, "text": name, "selector": sel})
    return {
        "url": page.url,
        "title": page.title() if hasattr(page, "title") else "",
        "clickables_preview": click_items,
        "has_accessibility_tree": axtree is not None,
    }

# --------------------
# Planners
# --------------------
def builtin_rule_planner(goal: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Very small rule-based planner for demo:
    - If goal mentions 'book' or a known category, it will open Books to Scrape
      and click the category then the first product and extract title/price.
    """
    g = (goal or "").lower()
    # map keywords → category link text
    cat = None
    for k, name in {
        "travel": "Travel",
        "music": "Music",
        "food": "Food and Drink",
        "poetry": "Poetry",
        "mystery": "Mystery"
    }.items():
        if k in g:
            cat = name
            break

    steps = [{"action": "goto", "url": "http://books.toscrape.com/"}]
    if cat:
        steps += [
            {"action": "click", "selector": f"role=link[name='{cat}']"},
            {"action": "wait_for", "selector": ".product_pod"},
            {"action": "click", "selector": ".product_pod a:first-of-type"},
            {"action": "wait_for", "selector": ".product_main h1"},
            {"action": "extract_text", "selector": ".product_main h1", "as": "title"},
            {"action": "extract_text", "selector": ".price_color", "as": "price"},
            {"action": "end"}
        ]
    else:
        # generic: click first clickable, then try to extract heading
        steps += [
            {"action": "wait_for", "selector": "a, button"},
            {"action": "click", "selector": "a, button"},
            {"action": "wait_for", "selector": "h1, h2"},
            {"action": "extract_text", "selector": "h1, h2", "as": "heading"},
            {"action": "end"}
        ]
    return {"steps": steps}

def openai_planner(goal: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Optional: use OpenAI to produce the plan. Requires OPENAI_API_KEY.
    Prompts the model to return ONLY valid JSON with 'steps'.
    """
    import json
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    sys = (
        "You are a browsing planner. Return ONLY JSON with a 'steps' array. "
        "Allowed actions: goto, click, type, wait_for, assert_text, extract_text, end. "
        "Use CSS or 'role=link[name=\"Text\"]' style selectors. Max 20 steps. "
        "Always end with an 'end' step."
    )
    user = f"Goal: {goal}\n\nPageContext:\n{json.dumps(ctx)[:4000]}"
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
        response_format={ "type": "json_object" },
        temperature=0
    )
    return json.loads(resp.choices[0].message.content)

# --------------------
# Executor
# --------------------
def execute_plan(plan: Dict[str, Any], headless: bool = True) -> Dict[str, Any]:
    err = validate_plan(plan)
    if err:
        return {"status": "error", "message": f"Invalid plan: {err}"}

    result: Dict[str, Any] = {"status": "success", "data": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            for i, step in enumerate(plan["steps"]):
                a = step["action"]
                timeout = int(step.get("timeout", DEFAULT_TIMEOUT))
                if a == "goto":
                    url = step["url"]
                    page.goto(url, timeout=timeout)
                    page.wait_for_load_state("domcontentloaded")
                elif a == "click":
                    page.locator(step["selector"]).first.click(timeout=timeout)
                elif a == "type":
                    page.locator(step["selector"]).first.fill(step.get("text", ""), timeout=timeout)
                elif a == "wait_for":
                    page.wait_for_selector(step["selector"], timeout=timeout)
                elif a == "assert_text":
                    t = page.locator(step["selector"]).first.text_content(timeout=timeout) or ""
                    if step.get("text", "").lower() not in t.lower():
                        raise AssertionError(f"assert_text failed at step {i}: '{step.get('text')}' not in '{t[:120]}'")
                elif a == "extract_text":
                    txt = page.locator(step["selector"]).first.text_content(timeout=timeout) or ""
                    key = step.get("as", f"field_{i}")
                    result["data"][key] = txt.strip()
                elif a == "end":
                    break
                else:
                    raise ValueError(f"Unknown action: {a}")
        except PWTimeout:
            browser.close()
            return {"status": "error", "message": "Timeout during execution."}
        except AssertionError as e:
            browser.close()
            return {"status": "error", "message": str(e)}
        except Exception as e:
            browser.close()
            return {"status": "error", "message": str(e)}
        browser.close()
    return result

# --------------------
# Orchestrate one run
# --------------------
def run_ai_goal(goal: str, planner: str = "builtin", headless: bool = True) -> Dict[str, Any]:
    """Make a context snapshot → get a plan → validate/execute → return result."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        # Start on an empty page to build initial context
        page.goto("about:blank")
        ctx0 = {"url": page.url, "title": "", "clickables_preview": [], "has_accessibility_tree": False}
        browser.close()

    # Get the plan
    if planner == "openai":
        # for the real thing, snapshot a real site if you want; using ctx0 is fine too
        plan = openai_planner(goal, ctx0)
    else:
        plan = builtin_rule_planner(goal, ctx0)

    # Execute
    return execute_plan(plan, headless=headless)
