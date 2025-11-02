# app.py
import os
import sqlite3
import traceback
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest
from jinja2 import TemplateNotFound

# ---- Optional imports (present if you kept these files) ----------------------
try:
    from robot_driver import search_product          # Playwright product flow
except Exception:
    def search_product(q: str) -> dict:
        return {"status": "error", "message": "robot_driver not available"}

try:
    from login_driver import run_login_test          # Demo login flow (optional)
except Exception:
    def run_login_test(**kwargs) -> dict:
        return {"status": "error", "message": "login_driver not available"}

# -----------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# ---- Security / runtime ------------------------------------------------------
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.permanent_session_lifetime = timedelta(minutes=30)

RELAXED_CSP = os.environ.get("RELAXED_CSP", "0") in ("1", "true", "True")
API_KEY = os.environ.get("API_KEY", "secret123")
MAX_CRED_LENGTH = 50
DB_PATH = os.path.join(BASE_DIR, "users.db")

# ---- Optional rate limiter ---------------------------------------------------
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])
except Exception:
    limiter = None

@app.after_request
def set_secure_headers(resp):
    # Relax CSP in dev when MCP/automation tools need to run
    if RELAXED_CSP:
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"
    else:
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp

@app.before_request
def make_session_permanent():
    session.permanent = True

# ---- DB helpers --------------------------------------------------------------
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
        # Seed default admin if missing
        cur.execute("SELECT 1 FROM users WHERE username = ?", ("admin",))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                ("admin", generate_password_hash("admin123"))
            )
            conn.commit()

def _safe_query(fn):
    try:
        return fn()
    except Exception as e:
        print(f"DB error: {e}")
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

# ---- Auth helpers ------------------------------------------------------------
def _too_long(x: str) -> bool:
    return x is None or len(x) > MAX_CRED_LENGTH

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

def api_or_login_required(json_only: bool = True):
    """
    Allow access if user is logged in OR correct X-API-Key provided.
    If json_only=True and unauthorized, return 401 JSON; otherwise redirect to /login.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            has_session = "user" in session
            has_api = request.headers.get("X-API-Key") == API_KEY
            if has_session or has_api:
                return view_func(*args, **kwargs)
            if json_only:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
            return redirect(url_for("login", next=request.path))
        return wrapper
    return decorator

# ---- Basic pages -------------------------------------------------------------
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))

# Login / Register / Logout
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
            flash(f"Credentials exceed {MAX_CRED_LENGTH} characters.", "error")
            return render_template("register.html"), 400
        if not username or not password:
            flash("Please fill out all fields.", "error")
        elif get_user(username):
            flash("Username already exists. Try logging in.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            ok = add_user(username, generate_password_hash(password))
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

# ---- Search page (HTML) ------------------------------------------------------
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
                    result = f"{data.get('title')} — {data.get('price')} ({data.get('meta','')})"
                else:
                    error = data.get("message", "Search failed.")
            except Exception as e:
                error = f"Search failed: {e}"
    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)

# ---- Categories (HTML + JSON) ------------------------------------------------
# Canonical list used by both HTML & JSON. Replace with your real categories if needed.
CATEGORIES = [
    "Travel", "Mystery", "Historical Fiction", "Sequential Art", "Classics",
    "Philosophy", "Romance", "Womens Fiction", "Fiction", "Childrens",
    "Religion", "Nonfiction", "Music", "Default", "Science", "Poetry"
]

@app.route("/categories", methods=["GET"])
@login_required  # HTML flow uses login
def categories_html():
    return render_template("categories.html", categories=CATEGORIES)

@app.route("/categories.json", methods=["GET"])
@api_or_login_required(json_only=True)  # <-- THIS removes the redirect for API calls
def categories_json():
    return jsonify({"status": "ok", "categories": CATEGORIES})

# ---- JSON APIs used by frontend/MCP -----------------------------------------
@app.route("/search-json", methods=["POST"])
@api_or_login_required(json_only=True)
def search_json():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    product_name = (data.get("product") or "").strip()
    result = search_product(product_name)
    return jsonify(result)

@app.route("/login-test", methods=["POST"])
@api_or_login_required(json_only=True)
def login_test():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    return jsonify(run_login_test(**data))

# ---- MCP “AI Brain” runner ---------------------------------------------------
@app.route("/api/run", methods=["POST"])
@api_or_login_required(json_only=True)
def mcp_run():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400
    goal = (data.get("goal") or "").strip()
    planner = (data.get("planner") or "builtin").lower()
    if not goal:
        return jsonify({"status": "error", "message": "Please provide a non-empty 'goal'."}), 400
    # If you have mcp_agent.py, import and call it; otherwise return a stub.
    try:
        from mcp_agent import run_ai_goal
        res = run_ai_goal(goal=goal, planner=planner, headless=True)
        return jsonify(res)
    except Exception as e:
        return jsonify({"status": "error", "message": f"MCP runner unavailable: {e}"}), 501

# ---- Health / version --------------------------------------------------------
@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})

@app.route("/api/version")
@api_or_login_required(json_only=True)
def api_version():
    return jsonify({"status": "ok", "version": "1.0.0"})

# ---- Errors ------------------------------------------------------------------
@app.errorhandler(404)
def _404(_e):
    try:
        return render_template("index.html"), 404
    except TemplateNotFound:
        return "<h2>Not found</h2>", 404

@app.errorhandler(500)
def _500(_e):
    try:
        return render_template("index.html"), 500
    except TemplateNotFound:
        return "<h2>Server error</h2>", 500

# ---- Run ---------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=True)
