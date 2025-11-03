# app.py
import os
import sqlite3
import traceback
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest
from jinja2 import TemplateNotFound

# Local drivers
from robot_driver import search_product  # Playwright product bot
from login_driver import run_login_test  # Playwright demo-login bot

# ------------------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# Security / general config
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB request cap
app.permanent_session_lifetime = timedelta(minutes=30)
DB_PATH = os.path.join(BASE_DIR, "users.db")

# Optional API key for JSON endpoints (set in env)
REQUIRED_API_KEY = os.environ.get("API_KEY")  # e.g., 'secret123'

# Content-Security-Policy (relax for MCP/local testing via RELAXED_CSP=1)
RELAXED_CSP = os.environ.get("RELAXED_CSP") in ("1", "true", "True")

# Default admin seed (local only)
SEED_ADMIN = os.environ.get("ADMIN_DEFAULT", "1") in ("1", "true", "True")

# Speed & UA (used by playbook runs)
CUSTOM_UA = (
    os.environ.get(
        "CUSTOM_UA",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
)

# Optional rate limiter (safe if unavailable)
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])
except Exception:
    limiter = None


# ------------------------------------------------------------------------------
# Security headers / session config
# ------------------------------------------------------------------------------
@app.after_request
def set_secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"

    if RELAXED_CSP:
        # relaxed for local MCP/automation
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data:; "
            "img-src 'self' data:; connect-src 'self' http://localhost:* http://127.0.0.1:*;"
        )
    else:
        # safer for normal runs
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:;"
        )
    return resp


@app.before_request
def make_session_permanent():
    session.permanent = True


# ------------------------------------------------------------------------------
# DB Helpers
# ------------------------------------------------------------------------------

def _normalize_search_payload(raw: dict, requested_category: str) -> dict:
    """
    Ensure the /search-json response always returns the new shape:
      { agent, status, category, items: [..], meta: {...} }
    If the old shape appears (single top-level title/price), coerce it.
    """
    if not isinstance(raw, dict):
        return {
            "agent": "BroncoMCP/1.0",
            "status": "error",
            "category": requested_category,
            "items": [],
            "meta": {"note": "Non-dict payload from driver; normalized to empty list"}
        }

    # If it already has "items" and it's a list, just pass through
    if isinstance(raw.get("items"), list):
        return raw

    # Legacy/flat shape: title/price/meta (string)
    title = raw.get("title")
    price = raw.get("price")
    status = raw.get("status", "success")
    agent = raw.get("agent", "BroncoMCP/1.0")

    # If we have a single item, wrap it into a list
    if title:
        items = [{"title": title, "price": price}]
    else:
        items = []

    # Try to convert meta when it's a string like "Category: Travel"
    meta = raw.get("meta")
    meta_out = {}
    if isinstance(meta, dict):
        meta_out = meta
    elif isinstance(meta, str):
        meta_out = {"legacy_meta": meta}

    return {
        "agent": agent,
        "status": status,
        "category": raw.get("category") or requested_category,
        "items": items,
        "meta": meta_out | {"normalized": True}
    }


def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )
            """)
            conn.commit()
        print(f"✅ Database initialized: {DB_PATH}")
    except Exception as e:
        print(f"❌ Database init failed: {e}")
        traceback.print_exc()


def _safe_query(fn):
    try:
        return fn()
    except sqlite3.OperationalError as e:
        app.logger.error(f"SQLite OperationalError: {e}")
        traceback.print_exc()
        return None
    except Exception as e:
        app.logger.error(f"Unknown DB error: {e}")
        traceback.print_exc()
        return None


def get_user(username: str):
    def _q():
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, password FROM users WHERE username = ?", (username,))
            return cur.fetchone()

    return _safe_query(_q)


def add_user(username: str, password_hash: str):
    def _q():
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            return True

    return _safe_query(_q)


def ensure_default_admin():
    """
    Local dev helper: seed an admin/admin123 account if ADMIN_DEFAULT=1.
    """
    if not SEED_ADMIN:
        return
    admin = get_user("admin")
    if not admin:
        try:
            add_user("admin", generate_password_hash("admin123"))
            print("✅ Seeded default admin user: admin / admin123")
        except Exception as e:
            print(f"⚠️ Failed to seed admin: {e}")


# ------------------------------------------------------------------------------
# Auth utilities
# ------------------------------------------------------------------------------
MAX_CRED_LENGTH = 50


def _too_long(x: str) -> bool:
    return x is None or len(x) > MAX_CRED_LENGTH


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def auth_or_api_key_ok() -> bool:
    """
    Allow either a logged-in session OR a valid X-API-Key header (if REQUIRED_API_KEY is set).
    """
    if "user" in session:
        return True
    if REQUIRED_API_KEY:
        provided = request.headers.get("X-API-Key")
        return provided == REQUIRED_API_KEY
    return False


# ------------------------------------------------------------------------------
# Routes: pages
# ------------------------------------------------------------------------------
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))


route_login = app.route("/login", methods=["GET", "POST"])
if limiter:
    route_login = limiter.limit("5 per minute")(route_login)


@route_login
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if _too_long(username) or _too_long(password):
            flash(f"Credentials exceed {MAX_CRED_LENGTH} characters.", "error")
            return render_template("login.html"), 400

        user = get_user(username)
        if user is None:
            flash("Database error — please try again later.", "error")
            return render_template("login.html"), 500

        if user and check_password_hash(user[1], password):
            session["user"] = username
            flash("Logged in successfully!", "success")
            return redirect(url_for("search_page"))

        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if _too_long(username) or _too_long(password):
            flash(f"Credentials exceed {MAX_CRED_LENGTH} characters.", "error")
            return render_template("register.html"), 400

        if not username or not password:
            flash("Please fill out all fields.", "error")
        elif get_user(username):
            flash("Username already exists. Try logging in.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            pw_hash = generate_password_hash(password)
            ok = add_user(username, pw_hash)
            if not ok:
                flash("Database error — please try again later.", "error")
                return render_template("register.html"), 500
            session["user"] = username
            flash("Account created successfully!", "success")
            return redirect(url_for("search_page"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


@app.route("/search", methods=["GET", "POST"])
@login_required
def search_page():
    """
    HTML page for the demo flow (Books to Scrape).
    If POST, it runs the product search via robot_driver and shows a card.
    """
    result = None
    error = None
    query = ""
    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        if not query:
            error = "Please type a product to search."
        else:
            try:
                data = search_product(query)
                if data.get("status") == "success":
                    # Format multiple items
                    items = data.get("items", [])
                    if items:
                        result = f"Found {len(items)} items in {data.get('category', 'category')}:\n"
                        for item in items[:5]:  # Show first 5
                            result += f"  • {item.get('title')} — {item.get('price')}\n"
                    else:
                        result = "No items found."
                else:
                    error = data.get("message", "Search failed.")
            except Exception as e:
                error = f"Search failed: {e}"
    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)


# NEW ROUTE: Demo console (the index.html page)
@app.route("/demo")
@login_required
def demo_index():
    """
    Serves the demo console (index.html) - the AJAX interface
    """
    return render_template("index.html")


# ------------------------------------------------------------------------------
# JSON APIs (session OR API key)
# ------------------------------------------------------------------------------

@app.route("/categories.json", methods=["GET"])
def categories_json():
    """
    Returns the list of Books to Scrape categories as JSON.
    Allowed for logged-in users or clients presenting X-API-Key.
    """
    if not auth_or_api_key_ok():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=CUSTOM_UA)
            page = ctx.new_page()
            page.goto("https://books.toscrape.com/", timeout=15000, wait_until="domcontentloaded")
            cats = page.eval_on_selector_all(
                "ul.nav-list li ul li a",
                "els => els.map(e => e.textContent.trim())"
            )
            browser.close()
        # De-duplicate / clean
        cats = [c for c in (cats or []) if c]
        return jsonify({"status": "success", "count": len(cats), "categories": cats}), 200
    except Exception as e:
        app.logger.exception("categories.json failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/search-json", methods=["POST"])
def search_json():
    """
    JSON API for product/category search used by MCP.
    - Accepts {"product": "..."} or {"category": "..."}
    - Always returns an 'items' list (never null/missing)
    - Includes 'status', 'agent', 'category', 'meta'
    - On scraper failure, returns items=[]
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    # Accept both keys
    category = (body.get("product") or body.get("category") or "").strip()
    limit = body.get("limit", 0)
    try:
        limit = int(limit)
    except Exception:
        limit = 0

    if not category:
        return jsonify({
            "agent": "BroncoMCP/1.0",
            "status": "error",
            "message": "Missing 'product' or 'category' in JSON payload.",
            "items": []
        }), 400

    # --- Call your scraper ---
    try:
        data = search_product(category)

        # Normalize the shape we expect
        items = data.get("items", [])
        if isinstance(items, dict):
            items = [items]
        elif not isinstance(items, list):
            items = []

        # Optional limit
        if limit and limit > 0:
            items = items[:limit]

        meta = data.get("meta", {})
        out = {
            "agent": data.get("agent", "BroncoMCP/1.0"),
            "status": data.get("status", "success"),
            "category": data.get("category", category),
            "items": items,
            "meta": meta
        }
        return jsonify(out), 200

    except Exception as e:
        # Fallback: safe empty result with error info
        print(f"[search-json] scraper error: {e}")
        return jsonify({
            "agent": "BroncoMCP/1.0",
            "status": "error",
            "category": category,
            "message": str(e),
            "items": [],
            "meta": {"note": "scraper failure; returned empty list"}
        }), 200


@app.route("/login-test", methods=["POST"])
def login_test():
    """
    JSON endpoint to run a demo login Playwright flow. Requires login or API key.
    """
    if not auth_or_api_key_ok():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if _too_long(username) or _too_long(password):
        msg = f"Possible buffer overflow attempt: username or password exceeds allowed length ({MAX_CRED_LENGTH})."
        app.logger.warning(msg)
        return jsonify({"status": "error", "message": msg}), 400

    result = run_login_test(username=username, password=password)
    return jsonify(result), 200 if result.get("status") == "success" else 500


# ------------------------------------------------------------------------------
# MCP "AI Brain" / health endpoints
# ------------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "agent": "BroncoMCP/1.0"}), 200


# --- /api/run: tolerant goal/steps runner for MCP "run_goal" ------------------
@app.route("/api/run", methods=["POST"])
def api_run():
    """
    Tolerant endpoint used by MCP "run_goal"-style tools.
    Accepts any of the following JSON shapes and never 500s on user error:

    A) {"goal": "<plain english instruction>", "planner":"builtin|openai", "headless": true}
    B) {"navigate": "http://example.com"}  or {"url": "http://example.com"}
    C) {"steps": [ {"action":"navigate","url":"..."}, ... ] }

    Returns:
      200 with a structured result on success
      400 with a structured error if payload is invalid
    """
    # Allow session or API key
    if not auth_or_api_key_ok():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    # ---- parse safely
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Body must be a JSON object."}), 400

    # tiny helper for uniform client errors
    def bad(msg, extra=None, code=400):
        payload = {"status": "error", "message": msg}
        if extra:
            payload["details"] = extra
        return jsonify(payload), code

    # Accept multiple shapes: goal / navigate / steps
    goal = (data.get("goal") or "").strip()
    navigate_url = data.get("navigate") or data.get("url")
    steps = data.get("steps")

    planner = (data.get("planner") or "builtin").lower()
    headless = bool(data.get("headless", True))

    # quick schema inference if tools send something unexpected
    if not goal and not navigate_url and not steps:
        if isinstance(data.get("action"), str) and data.get("action") == "navigate" and data.get("target"):
            navigate_url = data["target"]
        elif isinstance(data.get("actions"), list):
            steps = data["actions"]

    # case A: a plain goal → call your AI planner/runner
    if goal:
        try:
            from mcp_agent import run_ai_goal  # lazy import to keep startup fast
            result = run_ai_goal(goal=goal, planner=planner, headless=headless)
            return jsonify({
                "status": "success" if result.get("status") == "success" else "ok",
                "agent": "BroncoMCP/1.0",
                "planner": planner,
                "result": result,
            }), 200
        except Exception as e:
            app.logger.exception("run_ai_goal failed")
            return jsonify({
                "status": "error",
                "message": f"run_ai_goal failed: {e.__class__.__name__}",
            }), 500

    # case B: explicit navigate/url → do a minimal Playwright nav (fast)
    if navigate_url:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                ctx = browser.new_context(user_agent=CUSTOM_UA)
                page = ctx.new_page()
                page.goto(navigate_url, timeout=15000, wait_until="domcontentloaded")
                title = page.title()
                browser.close()
            return jsonify({
                "status": "success",
                "agent": "BroncoMCP/1.0",
                "action": "navigate",
                "url": navigate_url,
                "page_title": title
            }), 200
        except Exception as e:
            app.logger.exception("navigate failed")
            return bad("Navigation failed", {"error": str(e)}, code=502)

    # case C: a list of steps → implement a tiny dispatcher (support 'navigate' now)
    if isinstance(steps, list):
        try:
            from playwright.sync_api import sync_playwright
            outputs = []
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                ctx = browser.new_context(user_agent=CUSTOM_UA)
                page = ctx.new_page()
                for i, st in enumerate(steps, 1):
                    action = (st.get("action") or "").lower()
                    if action in ("navigate", "goto"):
                        url = st.get("url") or st.get("target")
                        if not url:
                            outputs.append({"step": i, "status": "error", "message": "navigate requires url"})
                            continue
                        page.goto(url, timeout=15000, wait_until="domcontentloaded")
                        outputs.append({"step": i, "status": "ok", "title": page.title()})
                    else:
                        outputs.append({"step": i, "status": "skipped", "action": action or "unknown"})
                browser.close()
            return jsonify({
                "status": "success",
                "agent": "BroncoMCP/1.0",
                "executed": outputs
            }), 200
        except Exception as e:
            app.logger.exception("steps execution failed")
            return bad("Steps execution failed", {"error": str(e)}, code=502)

    # if we got here, payload was understood but incomplete
    return bad(
        "Invalid payload for /api/run. Provide one of: "
        "{goal: string} | {navigate: url} | {steps: [ ... ]}",
        extra={"received_keys": list(data.keys())}
    )


# ------------------------------------------------------------------------------
# Error Pages
# ------------------------------------------------------------------------------
@app.errorhandler(404)
def _404(_e):
    return render_template("login.html"), 404


@app.errorhandler(500)
def _500(_e):
    return render_template("login.html"), 500


@app.errorhandler(TemplateNotFound)
def _template_missing(e):
    app.logger.error(f"Missing template: {e.name}")
    return "<h2>Template missing on server. Contact admin.</h2>", 500


# ------------------------------------------------------------------------------
# Run app
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n🚀 Starting Robot Driver API...")
    print(f"📁 Base directory: {BASE_DIR}")
    print(f"🗄️  Database: {DB_PATH}")
    print(f"🔐 Admin seeding: {'ENABLED' if SEED_ADMIN else 'DISABLED'}")
    print(f"🔑 API Key required: {'YES' if REQUIRED_API_KEY else 'NO'}")
    print("-" * 50)

    init_db()
    ensure_default_admin()

    print("\n✅ Server ready!")
    print("📍 Access at: http://localhost:5001")
    print("🔓 Login with: admin / admin123\n")

    # Use threaded mode for better performance with Playwright
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)