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

from robot_driver import search_product          # Playwright product bot
from login_driver import run_login_test          # Playwright demo-login bot

# ── App & paths ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# ── Security / limits ─────────────────────────────────────────────────────────
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB request cap
app.permanent_session_lifetime = timedelta(minutes=30)  # session timeout
MAX_CRED_LENGTH = 50  # username/password hard limit
DB_PATH = os.path.join(BASE_DIR, "users.db")

# (Optional) Rate limiter if installed; otherwise silently skipped
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])
except Exception:
    limiter = None


@app.after_request
def set_secure_headers(resp):
    # Solid defaults; relax CSP if you use external CDNs.
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp


@app.before_request
def make_session_permanent():
    session.permanent = True


# ── DB helpers ────────────────────────────────────────────────────────────────
def init_db():
    """Create users table if missing and seed a default admin user once."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        # ✅ Seed a default admin (override via env DEFAULT_USER / DEFAULT_PASS)
        default_user = os.getenv("DEFAULT_USER", "admin")
        default_pass = os.getenv("DEFAULT_PASS", "admin123")

        # Only insert if not already present
        cur.execute("SELECT 1 FROM users WHERE username = ?", (default_user,))
        exists = cur.fetchone()
        if not exists:
            pw_hash = generate_password_hash(default_pass)
            try:
                cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (default_user, pw_hash))
                print(f"✅ Default login added: {default_user} / {default_pass}")
            except sqlite3.IntegrityError:
                # Race-safe: if created by another process between SELECT and INSERT
                pass

        conn.commit()


def _safe_query(fn):
    """Wrap DB ops to avoid crashing the app on transient errors."""
    try:
        return fn()
    except sqlite3.OperationalError as e:
        print(f"❌ SQLite OperationalError: {e}")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"❌ Unknown DB error: {e}")
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


init_db()


# ── Auth utils ────────────────────────────────────────────────────────────────
def _too_long(x: str) -> bool:
    return x is None or len(x) > MAX_CRED_LENGTH


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


# ── Pages (classic flow) ──────────────────────────────────────────────────────
@app.route("/")
def home():
    # If you prefer the SPA demo as landing, return render_template("index.html") here.
    if "user" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))


route_login = app.route("/login", methods=["GET", "POST"])
if limiter:
    route_login = limiter.limit("5 per minute")(route_login)  # simple brute-force guard

@route_login
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if _too_long(username) or _too_long(password):
            flash(f"Possible buffer overflow attempt: credentials exceed {MAX_CRED_LENGTH} chars.", "error")
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
        confirm  = request.form.get("confirm") or ""

        if _too_long(username) or _too_long(password):
            flash(f"Possible buffer overflow attempt: credentials exceed {MAX_CRED_LENGTH} chars.", "error")
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
    """Protected page rendering search.html (classic form flow)."""
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
                    result = f"{data['title']} — {data['price']} ({data.get('meta','')})"
                else:
                    error = data.get("message", "Search failed.")
            except Exception as e:
                error = f"Search failed: {e}"
    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)


# Optional SPA demo page (AJAX → JSON APIs)
@app.route("/demo")
def demo_index():
    return render_template("index.html")


# ── JSON APIs (SPA) ───────────────────────────────────────────────────────────
@app.route("/search-json", methods=["POST"])
def search_json():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    product_name = (data.get("product") or "").strip()
    result = search_product(product_name)
    if result.get("status") == "success":
        print(f"✅ Success! {result.get('title')} — {result.get('price')} ({result.get('meta')})")
    else:
        print(f"❌ Error: {result.get('message')}")
    return jsonify(result)


@app.route("/login-test", methods=["POST"])
def login_test():
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
        print(f"❌ Security: {msg} username_len={len(username)} password_len={len(password)}")
        return jsonify({"status": "error", "message": msg}), 400

    result = run_login_test(username=username, password=password)
    return jsonify(result)


# ── MCP “AI Brain” endpoint ───────────────────────────────────────────────────
@app.route("/mcp/run", methods=["POST"])
def mcp_run():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

    goal = (data.get("goal") or "").strip()
    if not goal:
        return jsonify({"status": "error", "message": "Please provide a non-empty 'goal'."}), 400

    planner = (data.get("planner") or "builtin").lower()  # "builtin" or "openai"
    headless = not bool(os.environ.get("HEADFUL") in ("1", "true", "True"))

    # Import here to avoid Playwright import cost on app boot
    from mcp_agent import run_ai_goal
    result = run_ai_goal(goal=goal, planner=planner, headless=headless)
    return jsonify(result)


# ── Friendly error pages ──────────────────────────────────────────────────────
@app.errorhandler(404)
def _404(_e):
    return render_template("index.html"), 404

@app.errorhandler(500)
def _500(_e):
    return render_template("index.html"), 500

@app.errorhandler(TemplateNotFound)
def _template_missing(e):
    print(f"❌ Missing template: {e.name}")
    return "<h2>Template missing on server. Contact admin.</h2>", 500


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    # Use /register → /login → /search for classic flow, or /demo for SPA.
    app.run(host="0.0.0.0", port=5001, debug=True)
