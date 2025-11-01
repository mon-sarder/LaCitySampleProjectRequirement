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

from robot_driver import search_product, list_categories
from login_driver import run_login_test

# ────────────────────────── App setup ──────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.permanent_session_lifetime = timedelta(minutes=30)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True

MAX_CRED_LENGTH = 50
DB_PATH = os.path.join(BASE_DIR, "users.db")
AGENT_ID = "BroncoBot/1.0"
APP_VERSION = "1.0.0"

# Optional shared secret for API routes
API_KEY = os.environ.get("API_KEY")

# ──────────────────────── CSP (Dev vs Prod) ─────────────────────
# RELAXED_CSP=1 (default) is handy for Claude/MCP/local tooling
DEV_RELAXED_CSP = os.environ.get("RELAXED_CSP", "1") == "1"

@app.after_request
def set_secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"

    if DEV_RELAXED_CSP:
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src  'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "connect-src 'self' http://localhost:5001 http://127.0.0.1:5001 "
            "ws: wss: http://localhost:* http://127.0.0.1:*; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'self';"
        )
    else:
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'self';"
        )
    return resp

@app.before_request
def make_session_permanent():
    session.permanent = True

# ───────────────────────── DB helpers ──────────────────────────
def init_db():
    """Initialize DB and insert default admin if missing."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        cur.execute("SELECT username FROM users WHERE username=?", ("admin",))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                ("admin", generate_password_hash("admin123"))
            )
            print("✅ Default login added: admin / admin123")
        conn.commit()

def get_user(username):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, password FROM users WHERE username=?", (username,))
            return cur.fetchone()
    except Exception as e:
        print(f"❌ DB error: {e}")
        traceback.print_exc()
        return None

def add_user(username, pw_hash):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, pw_hash))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        print(f"❌ Add user error: {e}")
        traceback.print_exc()
        return False

init_db()

# ─────────────────────── Auth / decorators ─────────────────────
def _too_long(x: str) -> bool:
    return x is None or len(x) > MAX_CRED_LENGTH

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

def require_api_key(view):
    """Optional: protect API routes with X-API-Key header."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if API_KEY:
            client_key = request.headers.get("X-API-Key")
            if client_key != API_KEY:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapper

# ─────────────────────────── Routes ────────────────────────────
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))

# ── Login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if _too_long(username) or _too_long(password):
            flash(f"Possible buffer overflow attempt (>{MAX_CRED_LENGTH} chars).", "error")
            return render_template("login.html"), 400

        user = get_user(username)
        if user and check_password_hash(user[1], password):
            session["user"] = username
            flash("Logged in successfully!", "success")
            return redirect(url_for("search_page"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

# ── Register
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "")
        confirm  = (request.form.get("confirm")  or "")

        if not username or not password or not confirm:
            flash("Please fill out all fields.", "error")
            return render_template("register.html", username=username), 400

        if _too_long(username) or _too_long(password) or _too_long(confirm):
            flash(f"Username or password exceeds {MAX_CRED_LENGTH} characters.", "error")
            return render_template("register.html", username=username), 400

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("register.html", username=username), 400

        if get_user(username):
            flash("Username already exists.", "error")
            return render_template("register.html", username=username), 400

        pw_hash = generate_password_hash(password)
        if add_user(username, pw_hash):
            session["user"] = username
            flash("Account created successfully!", "success")
            return redirect(url_for("search_page"))
        else:
            flash("Database error — try again later.", "error")
            return render_template("register.html", username=username), 500

    return render_template("register.html")

# ── Logout
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# ── Search (with category chips)
@app.route("/search", methods=["GET", "POST"])
@login_required
def search_page():
    ctx = {
        "username": session.get("user"),
        "query": request.args.get("query", ""),  # supports /search?query=Category
        "error": None, "message": None,
        "choices": None, "items": None, "picked": None, "meta": None,
    }

    # Pre-filled from /categories click
    if request.method == "GET" and ctx["query"]:
        try:
            data = search_product(ctx["query"], agent=AGENT_ID)
            status = data.get("status")
            if status == "choices":
                ctx["message"] = data.get("message")
                ctx["choices"] = data.get("categories") or []
            elif status == "success":
                ctx["picked"] = data.get("category")
                ctx["items"]  = data.get("items") or []
                ctx["meta"]   = data.get("meta")
        except Exception as e:
            ctx["error"] = f"Search failed: {e}"
        return render_template("search.html", **ctx)

    if request.method == "POST":
        if request.form.get("list_all") == "1":
            try:
                data = list_categories(agent=AGENT_ID)
                ctx["message"] = data.get("message") or "Available categories:"
                ctx["choices"] = data.get("categories") or []
            except Exception as e:
                ctx["error"] = f"Failed to fetch categories: {e}"
            return render_template("search.html", **ctx)

        q = (request.form.get("query") or "").strip()
        ctx["query"] = q
        if not q:
            ctx["error"] = "Please type a product/category to search."
        else:
            try:
                data = search_product(q, agent=AGENT_ID)
                status = data.get("status")
                if status == "choices":
                    ctx["message"] = data.get("message")
                    ctx["choices"] = data.get("categories") or []
                elif status == "success":
                    ctx["picked"] = data.get("category")
                    ctx["items"]  = data.get("items") or []
                    ctx["meta"]   = data.get("meta")
                else:
                    ctx["error"] = data.get("message", "Search failed.")
            except Exception as e:
                ctx["error"] = f"Search failed: {e}"

    return render_template("search.html", **ctx)

# ── Categories (HTML + JSON)
@app.route("/categories")
@login_required
def categories_page():
    try:
        data = list_categories(agent=AGENT_ID)
        cats = data.get("categories", [])
    except Exception as e:
        cats = []
        flash(f"Failed to load categories: {e}", "error")
    return render_template("categories.html", categories=cats)

@app.route("/categories.json")
@login_required
def categories_json():
    try:
        data = list_categories(agent=AGENT_ID)
        return jsonify({"status": "choices", "categories": data.get("categories", [])})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ── JSON helpers
@app.route("/search-json", methods=["POST"])
def search_json():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON."}), 400
    q = (data.get("product") or "").strip()
    return jsonify(search_product(q))

@app.route("/login-test", methods=["POST"])
def login_test():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON."}), 400
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if _too_long(username) or _too_long(password):
        return jsonify({"status": "error", "message": "Input too long."}), 400
    return jsonify(run_login_test(username=username, password=password))

# ── MCP bridge
@app.route("/mcp/run", methods=["POST"])
def mcp_run():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400
    goal = (data.get("goal") or "").strip()
    if not goal:
        return jsonify({"status": "error", "message": "Missing 'goal'."}), 400
    from mcp_agent import run_ai_goal
    result = run_ai_goal(goal=goal, planner=data.get("planner", "builtin"), headless=True)
    return jsonify(result)

# ── Shareable API (Challenge 2)
@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})

@app.route("/api/version")
def api_version():
    return jsonify({"status": "ok", "version": APP_VERSION})

@app.route("/api/run", methods=["POST"])
@require_api_key
def api_run():
    """
    POST JSON: { "goal": "...", "planner": "builtin" }
    Returns: execution result from the AI runner.
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

    goal = (data.get("goal") or "").strip()
    if not goal:
        return jsonify({"status": "error", "message": "Missing 'goal'."}), 400

    planner = (data.get("planner") or "builtin").lower()
    from mcp_agent import run_ai_goal
    result = run_ai_goal(goal=goal, planner=planner, headless=True)
    return jsonify(result)

@app.route("/launch", methods=["GET"])
@require_api_key
def launch_link():
    """
    GET /launch?goal=List%20categories&planner=builtin
    Handy "launch link" to trigger a run from a URL.
    """
    goal = (request.args.get("goal") or "").strip()
    if not goal:
        return jsonify({"status": "error", "message": "Provide ?goal=..."}), 400
    planner = (request.args.get("planner") or "builtin").lower()
    from mcp_agent import run_ai_goal
    result = run_ai_goal(goal=goal, planner=planner, headless=True)
    return jsonify({"status": "ok", "goal": goal, "result": result})

# ── Errors
@app.errorhandler(404)
def _404(_e):
    return render_template("index.html"), 404

@app.errorhandler(500)
def _500(_e):
    return render_template("index.html"), 500

@app.errorhandler(TemplateNotFound)
def _template_missing(e):
    print(f"❌ Missing template: {e.name}")
    return "<h2>Template missing. Contact admin.</h2>", 500

# ── Run
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=True)
