# app.py
import os
import sqlite3
import traceback
from datetime import timedelta
from functools import wraps
import time
from typing import List, Dict, Any

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest
from jinja2 import TemplateNotFound

# --- Optional: your Playwright driver(s) if present
try:
    from robot_driver import search_product  # returns dict JSON for product/category
except Exception:
    # Safe fallback stub so the app never 500s:
    def search_product(query: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "message": "Playwright driver not available",
            "query": query,
        }

# ──────────────────────────────────────────────────────────────
# App & Security
# ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB request cap
app.permanent_session_lifetime = timedelta(minutes=30)

API_KEY = os.environ.get("API_KEY", "secret123")  # <- Claude should pass this in X-API-Key
RELAXED_CSP = os.environ.get("RELAXED_CSP", "0") in ("1", "true", "True")
DB_PATH = os.path.join(BASE_DIR, "users.db")

# ──────────────────────────────────────────────────────────────
# Headers / Security
# ──────────────────────────────────────────────────────────────

@app.after_request
def set_secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if RELAXED_CSP:
        # Allow Claude/agent tools to fetch your endpoints freely during MCP runs
        resp.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:"
    else:
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp

def api_auth_ok() -> bool:
    """API endpoints must use API key. Prevent HTML login redirects."""
    key = request.headers.get("X-API-Key")
    return bool(key and key == API_KEY)

def api_unauthorized():
    return jsonify({"status": "error", "message": "Unauthorized"}), 401

@app.before_request
def make_session_permanent():
    session.permanent = True

# ──────────────────────────────────────────────────────────────
# DB helpers & seed admin
# ──────────────────────────────────────────────────────────────

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
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, password FROM users WHERE username = ?", (username,))
        return cur.fetchone()

def add_user(username: str, password_hash: str):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        return True

def ensure_default_admin():
    """Seed default admin only if missing, or use env ADMIN_USER/PASS."""
    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASS", "admin123")
    if not get_user(admin_user):
        try:
            add_user(admin_user, generate_password_hash(admin_pass))
            print(f"[seed] Created default admin '{admin_user}'")
        except Exception as e:
            print(f"[seed] Could not create default admin: {e}")

init_db()
ensure_default_admin()

# ──────────────────────────────────────────────────────────────
# Auth utils & pages
# ──────────────────────────────────────────────────────────────

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

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
        if not username or not password:
            flash("Please fill out all fields.", "error")
        elif get_user(username):
            flash("Username already exists. Try logging in.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            try:
                pw_hash = generate_password_hash(password)
                add_user(username, pw_hash)
                session["user"] = username
                flash("Account created successfully!", "success")
                return redirect(url_for("search_page"))
            except sqlite3.IntegrityError:
                flash("Username already exists.", "error")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

# ──────────────────────────────────────────────────────────────
# Search page (manual)
# ──────────────────────────────────────────────────────────────

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
                    result = data
                else:
                    error = data.get("message", "Search failed.")
            except Exception as e:
                error = f"Search failed: {e}"
    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)

# ──────────────────────────────────────────────────────────────
# Categories: robust default fallback
# ──────────────────────────────────────────────────────────────

DEFAULT_CATEGORIES: List[str] = [
    "Travel", "Mystery", "Historical Fiction", "Sequential Art", "Classics", "Philosophy",
    "Romance", "Womens Fiction", "Fiction", "Childrens", "Religion", "Nonfiction",
    "Music", "Default", "Science Fiction", "Sports and Games", "Add a comment",
    "Fantasy", "New Adult", "Young Adult", "Science", "Poetry", "Paranormal",
    "Art", "Autobiography", "Parenting", "Adult Fiction", "Humor", "Horror",
    "History", "Food and Drink", "Christian Fiction", "Business", "Biography",
    "Thriller", "Contemporary", "Spirituality", "Academic", "Self Help",
    "Historical", "Christian", "Suspense", "Short Stories", "Novels", "Health",
    "Politics", "Cultural", "Erotica", "Crime"
]

def list_categories() -> List[str]:
    """
    If you already scrape categories elsewhere, call it here.
    For now, we return a static robust list so MCP never sees an empty payload.
    """
    return DEFAULT_CATEGORIES[:]

# ──────────────────────────────────────────────────────────────
# JSON API endpoints (MCP-facing). Always JSON + API Key.
# ──────────────────────────────────────────────────────────────

@app.get("/categories.json")
def categories_json():
    if not api_auth_ok():
        return api_unauthorized()

    try:
        cats = list_categories()
        if not cats:
            cats = DEFAULT_CATEGORIES
        payload = {
            "status": "success",
            "agent": "BroncoMCP/1.0",
            "count": len(cats),
            "categories": cats,
            "timestamp": int(time.time())
        }
        return jsonify(payload), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Failed to load categories.",
            "detail": str(e)
        }), 500

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

    product_name = (data.get("product") or "").strip()
    try:
        result = search_product(product_name)
    except Exception as e:
        result = {"status": "error", "message": f"Search failed: {e}"}
    return jsonify(result), 200

@app.post("/api/run")
def api_run():
    """
    Simple 'accept goal' endpoint so you never get a 500.
    You can extend this to a real planner if desired.
    """
    if not api_auth_ok():
        return api_unauthorized()

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    goal = (data.get("goal") or "").strip()
    headless = bool(data.get("headless", True))
    plan = data.get("plan", [])

    return jsonify({
        "status": "accepted",
        "agent": "BroncoMCP/1.0",
        "goal": goal,
        "headless": headless,
        "plan_steps": len(plan),
        "timestamp": int(time.time())
    }), 200

@app.get("/api/health")
def api_health():
    return jsonify({"status": "ok", "agent": "BroncoMCP/1.0", "timestamp": int(time.time())}), 200

# ──────────────────────────────────────────────────────────────
# Error Pages
# ──────────────────────────────────────────────────────────────

@app.errorhandler(404)
def _404(_e):
    # Show a friendly page, but keep it simple
    return render_template("index.html"), 404

@app.errorhandler(500)
def _500(_e):
    return render_template("index.html"), 500

@app.errorhandler(TemplateNotFound)
def _template_missing(e):
    print(f"❌ Missing template: {e.name}")
    return "<h2>Template missing on server. Contact admin.</h2>", 500

# ──────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    ensure_default_admin()
    app.run(host="0.0.0.0", port=5001, debug=True)
