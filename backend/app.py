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

# Your Playwright robot modules
import robot_driver as rd           # so we can try multiple fns for categories
from robot_driver import search_product

# ──────────────────────────────────────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB
app.permanent_session_lifetime = timedelta(minutes=30)

DB_PATH = os.path.join(BASE_DIR, "users.db")
MAX_CRED_LENGTH = 50
API_KEY = os.environ.get("API_KEY", "secret123")

# Optional: small CSP helper (relax if env set)
RELAXED_CSP = os.environ.get("RELAXED_CSP", "").lower() in ("1", "true", "yes")

@app.after_request
def set_secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if RELAXED_CSP:
        # allow inline for local testing/tools
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    else:
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp

@app.before_request
def make_session_permanent():
    session.permanent = True

# ──────────────────────────────────────────────────────────────────────────────
# DB utilities
# ──────────────────────────────────────────────────────────────────────────────
def init_db():
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

def _safe_query(fn):
    try:
        return fn()
    except Exception as e:
        print(f"[DB] {e}")
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

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _too_long(x: str) -> bool:
    return x is None or len(x) > MAX_CRED_LENGTH

def _get_categories_safe():
    """
    Try several possible functions in robot_driver to get categories.
    Normalize to a list[str] so jsonify always succeeds.
    """
    for fn_name in ("get_categories", "list_categories", "fetch_categories"):
        if hasattr(rd, fn_name):
            try:
                cats = getattr(rd, fn_name)()
                # normalize
                if isinstance(cats, dict) and "categories" in cats:
                    cats = cats["categories"]
                if isinstance(cats, (set, tuple)):
                    cats = list(cats)
                if not isinstance(cats, list):
                    cats = list(cats)
                return [str(c).strip() for c in cats if str(c).strip()]
            except Exception as e:
                print(f"[categories] {fn_name} failed: {e}")
                traceback.print_exc()
    return []

def api_or_login_required(view):
    """
    If X-API-Key matches, allow without session.
    If logged in, allow.
    Otherwise:
      - for API paths return 401 JSON (no HTML redirect)
      - for pages redirect to login
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if api_key and api_key == API_KEY:
            return view(*args, **kwargs)
        if "user" in session:
            return view(*args, **kwargs)
        if request.path.endswith(".json") or request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        return redirect(url_for("login", next=request.full_path))
    return wrapper

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper

# ──────────────────────────────────────────────────────────────────────────────
# Routes: UI navigation
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if _too_long(username) or _too_long(password):
            flash(f"Credentials exceed {MAX_CRED_LENGTH} characters.", "error")
            return render_template("login.html"), 400
        user = get_user(username)
        if user and check_password_hash(user[1], password):
            session["user"] = username
            flash("Logged in successfully!", "success")
            # Default admin seeding (optional)
            # seed_admin()  # if you added a helper
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
            if not add_user(username, pw_hash):
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

# Optional SPA demo (AJAX)
@app.route("/demo")
def demo_index():
    return render_template("index.html")

# ──────────────────────────────────────────────────────────────────────────────
# JSON APIs (used by MCP bridge & SPA)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def api_health():
    return jsonify({"status": "ok"})

@app.get("/categories.json")
@api_or_login_required
def categories_json():
    try:
        cats = _get_categories_safe()
        return jsonify({"status": "ok", "categories": cats})
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"categories failed: {e}",
            "trace": traceback.format_exc().splitlines()[-5:]
        }), 500

@app.post("/search-json")
@api_or_login_required
def search_json():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    product_name = (data.get("product") or "").strip()
    try:
        result = search_product(product_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Search failed: {e}"}), 500

@app.post("/api/run")
@api_or_login_required
def api_run():
    data = request.get_json(silent=True) or {}
    goal = (data.get("goal") or "").strip()
    planner = (data.get("planner") or "builtin").lower()
    if not goal:
        return jsonify({"status": "error", "message": "Missing 'goal'"}), 400

    headless = not (os.environ.get("HEADFUL", "").lower() in ("1", "true", "yes"))

    try:
        from mcp_agent import run_ai_goal
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"mcp_agent import failed: {e}",
            "trace": traceback.format_exc().splitlines()[-5:]
        }), 500

    try:
        result = run_ai_goal(goal=goal, planner=planner, headless=headless)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"/api/run failed: {e}",
            "trace": traceback.format_exc().splitlines()[-8:]
        }), 500

# ──────────────────────────────────────────────────────────────────────────────
# Friendly error pages
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    # Optional: seed a default admin once
    if not get_user("admin"):
        add_user("admin", generate_password_hash("admin123"))
    app.run(host="0.0.0.0", port=5001, debug=True)
