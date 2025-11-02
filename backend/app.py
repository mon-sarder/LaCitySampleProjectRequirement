# app.py (final)
import os
import time
import json
import sqlite3
import traceback
from functools import wraps
from datetime import timedelta

import requests
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest
from jinja2 import TemplateNotFound

# Your Playwright driver(s)
# - search_product(query) : dict
# - list_categories()     : list[str]  (optional; we also implement an HTTP fallback below)
try:
    from robot_driver import search_product  # noqa
except Exception:
    # Fallback dummy so the server still boots if playwright isn't ready
    def search_product(q):
        return {
            "status": "success",
            "title": f"(demo) {q or 'N/A'}",
            "price": "£9.99",
            "meta": "demo",
        }

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# ───────────── Security / session
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.permanent_session_lifetime = timedelta(minutes=30)

# Optional API key (protects JSON API routes)
API_KEY = os.environ.get("API_KEY", "secret123")

# Relax CSP to help MCP/browser tools if needed
RELAXED_CSP = os.environ.get("RELAXED_CSP", "0") in ("1", "true", "True")

# ───────────── SQLite (users)
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
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, password FROM users WHERE username = ?", (username,))
        return cur.fetchone()

def add_user(username: str, password_hash: str):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password_hash))
        conn.commit()

def ensure_admin_bootstrap():
    """Create default admin:admin if missing (disable this in prod)."""
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASS", "admin")
    if not get_user(username):
        add_user(username, generate_password_hash(password))

init_db()
ensure_admin_bootstrap()

# ───────────── Headers
@app.after_request
def set_secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if RELAXED_CSP:
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:;"
        )
    else:
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp

@app.before_request
def make_session_permanent():
    session.permanent = True

# ───────────── Auth helpers (web pages)
def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

# ───────────── API key helpers (JSON API)
def api_auth_ok():
    # Allow local loopback without key if you want (toggle with ALLOW_LOCAL_NO_KEY=1)
    allow_local = os.environ.get("ALLOW_LOCAL_NO_KEY", "0") in ("1", "true", "True")
    if allow_local:
        if request.remote_addr in ("127.0.0.1", "::1", None):
            return True
    token = request.headers.get("X-API-Key") or request.args.get("api_key")
    return token == API_KEY

def api_unauthorized():
    return jsonify({"status": "error", "message": "Unauthorized"}), 401

# ───────────── Categories (fallbacks)
DEFAULT_CATEGORIES = [
    "Travel", "Mystery", "Historical Fiction", "Sequential Art", "Classics",
    "Philosophy", "Romance", "Womens Fiction", "Fiction", "Childrens"
]

def list_categories_http_fallback():
    """
    Try to fetch categories directly from Books to Scrape.
    If offline/unavailable, return DEFAULT_CATEGORIES.
    """
    try:
        html = requests.get("https://books.toscrape.com/index.html", timeout=6).text
        # Simple parse for category names in the side menu
        # (avoid heavy dependencies; quick & dirty)
        names = []
        anchor_marker = '<a href="catalogue/category/books/'
        for line in html.splitlines():
            if anchor_marker in line and "</a>" in line:
                # e.g.: <a href="catalogue/category/books/travel_2/index.html"> Travel</a>
                text = line.split(">")[-1].split("<")[0].strip()
                if text and text.lower() != "books":
                    names.append(text)
        if names:
            return names
    except Exception:
        pass
    return DEFAULT_CATEGORIES

# ───────────── Web pages (UI)
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
            add_user(username, generate_password_hash(password))
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
    return render_template("search.html",
                           username=session.get("user"),
                           result=result,
                           error=error,
                           query=query)

# ───────────── JSON API (protected by X-API-Key)
@app.get("/api/health")
def api_health():
    if not api_auth_ok():
        return api_unauthorized()
    return jsonify({"status": "ok", "agent": "BroncoMCP/1.0", "timestamp": int(time.time())}), 200

@app.get("/categories.json")
def categories_json():
    if not api_auth_ok():
        return api_unauthorized()
    try:
        cats = list_categories_http_fallback()
        payload = {
            "status": "success",
            "agent": "BroncoMCP/1.0",
            "count": len(cats),
            "categories": cats,
            "timestamp": int(time.time()),
        }
        resp = jsonify(payload)
        # Ensure this never becomes an HTML redirect or partial body
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Connection"] = "close"
        return resp, 200
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
        return jsonify({"status": "error", "message": "Invalid JSON."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    product = (data.get("product") or "").strip()
    if not product:
        return jsonify({"status": "error", "message": "Missing 'product'."}), 400

    try:
        result = search_product(product)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"Search failed: {e}"}), 500

@app.post("/api/run")
def api_run():
    """
    Patched: never 500s on missing/invalid JSON.
    Returns a well-formed acceptance response so tools like Claude can proceed.
    """
    if not api_auth_ok():
        return api_unauthorized()

    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    goal = (data.get("goal") or "N/A").strip()
    headless = bool(data.get("headless", True))
    plan = data.get("plan", [])

    response = {
        "status": "accepted",
        "agent": "BroncoMCP/1.0",
        "goal": goal,
        "headless": headless,
        "plan_steps": len(plan),
        "timestamp": int(time.time()),
    }
    return jsonify(response), 200

# ───────────── Error handling
@app.errorhandler(404)
def _404(_e):
    # For API paths, return JSON
    if request.path.startswith("/api") or request.path.endswith(".json"):
        return jsonify({"status": "error", "message": "Not Found"}), 404
    # Otherwise show index/login
    try:
        return render_template("index.html"), 404
    except TemplateNotFound:
        return render_template("login.html"), 404

@app.errorhandler(500)
def _500(_e):
    if request.path.startswith("/api") or request.path.endswith(".json"):
        return jsonify({"status": "error", "message": "Server error"}), 500
    try:
        return render_template("index.html"), 500
    except TemplateNotFound:
        return "<h2>Server error.</h2>", 500

# ───────────── Main
if __name__ == "__main__":
    # In dev: flask run on 0.0.0.0:5001
    app.run(host="0.0.0.0", port=5001, debug=True)
