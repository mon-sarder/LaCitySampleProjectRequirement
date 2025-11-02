# app.py
import os
import time
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

# Local robot driver modules
# Expected to export:
#   - search_product(query: str) -> dict
#   - list_categories() -> list[str]
try:
    from robot_driver import search_product, list_categories  # type: ignore
except Exception:
    # Soft fallback to keep server booting even if driver not ready
    def search_product(_q: str) -> dict:
        return {
            "status": "error",
            "message": "robot_driver.search_product not available."
        }

    def list_categories() -> list:
        return []

# ── App setup ─────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# Security / session
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB
app.permanent_session_lifetime = timedelta(minutes=30)

# Simple brute-force guard if available
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])
except Exception:
    limiter = None

# API key protection for machine endpoints
API_KEY = os.environ.get("API_KEY", "secret123").strip()

def api_auth_ok() -> bool:
    # Header name chosen to be explicit and common
    return request.headers.get("X-API-Key", "") == API_KEY

def api_unauthorized():
    return jsonify({"status": "error", "message": "Unauthorized"}), 401

# Basic security headers (relax if you embed cross origins)
@app.after_request
def set_secure_headers(resp):
    # reasonable defaults; adjust CSP if needed
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # allow same-origin inline scripts/styles created by Flask templates
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    )
    return resp

@app.before_request
def make_session_permanent():
    session.permanent = True

# ── SQLite users ──────────────────────────────────────────────────────────────
DB_PATH = os.path.join(BASE_DIR, "users.db")

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

def get_user(username: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, password FROM users WHERE username = ?", (username,))
            return cur.fetchone()
    except Exception:
        traceback.print_exc()
        return None

def add_user(username: str, password_hash: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            return True
    except Exception:
        traceback.print_exc()
        return False

def seed_default_admin():
    """Create default admin (admin / admin123) if not present."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users WHERE username=?", ("admin",))
            exists = cur.fetchone()[0]
            if not exists:
                cur.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    ("admin", generate_password_hash("admin123"))
                )
                conn.commit()
    except Exception:
        traceback.print_exc()

init_db()
seed_default_admin()

# ── Auth helpers ──────────────────────────────────────────────────────────────
MAX_CRED_LENGTH = 50

def too_long(value: str) -> bool:
    return value is None or len(value) > MAX_CRED_LENGTH

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

# ── Web pages ────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return redirect(url_for("search_page") if "user" in session else url_for("login"))

route_login = app.route("/login", methods=["GET", "POST"])
if limiter:
    route_login = limiter.limit("5 per minute")(route_login)

@route_login
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if too_long(username) or too_long(password):
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

        if too_long(username) or too_long(password):
            flash(f"Credentials exceed {MAX_CRED_LENGTH} characters.", "error")
            return render_template("register.html"), 400

        if not username or not password:
            flash("Please fill out all fields.", "error")
        elif get_user(username):
            flash("Username already exists. Try logging in.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            if add_user(username, generate_password_hash(password)):
                session["user"] = username
                flash("Account created successfully!", "success")
                return redirect(url_for("search_page"))
            flash("Database error — please try again later.", "error")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

# ── Web search page (form flow) ───────────────────────────────────────────────
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
                res = search_product(query)
                if res.get("status") == "success":
                    result = f"{res.get('title','')} — {res.get('price','')} {res.get('meta','')}"
                else:
                    error = res.get("message", "Search failed.")
            except Exception as e:
                traceback.print_exc()
                error = f"Search failed: {e}"
    return render_template("search.html",
                           username=session.get("user"),
                           result=result, error=error, query=query)

# ── JSON APIs for SPA / MCP ───────────────────────────────────────────────────
@app.post("/search-json")
def search_json():
    if not api_auth_ok():
        return api_unauthorized()
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    query = (data.get("product") or "").strip()
    result = search_product(query)
    return jsonify(result), 200

@app.get("/categories.json")
def categories_json():
    if not api_auth_ok():
        return api_unauthorized()
    try:
        cats = list_categories() or []
        return jsonify({
            "status": "success",
            "count": len(cats),
            "categories": cats,
            "agent": "BroncoMCP/1.0",
            "timestamp": int(time.time())
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Failed to list categories: {e}"}), 500

# ── Hardened /api endpoints for Claude MCP ────────────────────────────────────
@app.get("/api/health")
def api_health():
    if not api_auth_ok():
        return api_unauthorized()

    payload = {
        "status": "ok",
        "agent": "BroncoMCP/1.0",
        "timestamp": int(time.time()),
        "endpoints": ["/api/run", "/categories.json", "/search-json"]
    }
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200

@app.post("/api/run")
def api_run():
    """
    Safe goal runner for Claude MCP.
    Handles empty/malformed/missing JSON gracefully.
    Always returns valid JSON (never 500).
    """
    if not api_auth_ok():
        return api_unauthorized()

    try:
        data = request.get_json(force=False, silent=True)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    goal = (data.get("goal") or "N/A").strip()
    headless = bool(data.get("headless", True))
    plan = data.get("plan", [])

    meta = {
        "method": request.method,
        "path": request.path,
        "client_ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
    }

    response = {
        "status": "accepted",
        "agent": "BroncoMCP/1.0",
        "goal": goal,
        "headless": headless,
        "plan_steps": len(plan),
        "timestamp": int(time.time()),
        "meta": meta,
    }
    resp = jsonify(response)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Connection"] = "close"
    return resp, 200

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def _404(_e):
    try:
        return render_template("index.html"), 404
    except TemplateNotFound:
        return "<h3>Not found</h3>", 404

@app.errorhandler(500)
def _500(_e):
    try:
        return render_template("index.html"), 500
    except TemplateNotFound:
        return "<h3>Server error</h3>", 500

@app.errorhandler(TemplateNotFound)
def _template_missing(e):
    print(f"❌ Missing template: {e.name}")
    return "<h3>Template missing on server.</h3>", 500

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    seed_default_admin()
    # Host/port align with your Docker run -p 5001:5001
    app.run(host="0.0.0.0", port=5001, debug=True)
