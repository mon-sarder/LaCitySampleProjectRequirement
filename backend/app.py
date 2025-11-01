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

from robot_driver import search_product
from login_driver import run_login_test

# ── App setup ────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.permanent_session_lifetime = timedelta(minutes=30)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
MAX_CRED_LENGTH = 50
DB_PATH = os.path.join(BASE_DIR, "users.db")
AGENT_ID = "BroncoBot/1.0"

# ── Security headers ─────────────────────────────────────────
@app.after_request
def set_secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp

@app.before_request
def make_session_permanent():
    session.permanent = True

# ── Database helpers ─────────────────────────────────────────
def init_db():
    """Initialize DB and insert default admin user if not exists."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        default_user = "admin"
        default_pass = "admin123"
        cur.execute("SELECT username FROM users WHERE username=?", (default_user,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (default_user, generate_password_hash(default_pass))
            )
            print(f"✅ Default login added: {default_user} / {default_pass}")
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

# ── Auth helpers ─────────────────────────────────────────────
def _too_long(x: str):
    return x is None or len(x) > MAX_CRED_LENGTH

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

# ── Routes ───────────────────────────────────────────────────
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
            flash(f"Possible buffer overflow attempt (>{MAX_CRED_LENGTH} chars).", "error")
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
        # Robust trim of all fields
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "")
        confirm  = (request.form.get("confirm")  or "")

        # 1) Required fields first
        if not username or not password or not confirm:
            flash("Please fill out all fields.", "error")
            return render_template("register.html",
                                   username=username), 400

        # 2) Buffer/overflow limit
        if _too_long(username) or _too_long(password) or _too_long(confirm):
            flash(f"Username or password exceeds {MAX_CRED_LENGTH} characters.", "error")
            return render_template("register.html",
                                   username=username), 400

        # 3) Passwords must match
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("register.html",
                                   username=username), 400

        # 4) Username must be unique
        if get_user(username):
            flash("Username already exists.", "error")
            return render_template("register.html",
                                   username=username), 400

        # 5) Create user
        pw_hash = generate_password_hash(password)
        if add_user(username, pw_hash):
            session["user"] = username
            flash("Account created successfully!", "success")
            return redirect(url_for("search_page"))
        else:
            flash("Database error — try again later.", "error")
            return render_template("register.html",
                                   username=username), 500

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# ── Enhanced Search with category button ─────────────────────
@app.route("/search", methods=["GET", "POST"])
@login_required
def search_page():
    context = {
        "username": session.get("user"),
        "query": "",
        "error": None,
        "message": None,
        "choices": None,
        "items": None,
        "picked": None,
        "meta": None,
    }

    if request.method == "POST":
        # Show available categories button
        if request.form.get("list_all") == "1":
            try:
                data = search_product("", agent=AGENT_ID)
                context["message"] = data.get("message") or "Available categories:"
                context["choices"] = data.get("categories") or []
            except Exception as e:
                context["error"] = f"Failed to fetch categories: {e}"
            return render_template("search.html", **context)

        q = (request.form.get("query") or "").strip()
        context["query"] = q
        if not q:
            context["error"] = "Please type a product/category to search."
        else:
            try:
                data = search_product(q, agent=AGENT_ID)
                status = data.get("status")
                if status == "choices":
                    context["message"] = data.get("message")
                    context["choices"] = data.get("categories") or []
                elif status == "success":
                    context["picked"] = data.get("category")
                    context["items"] = data.get("items") or []
                    context["meta"] = data.get("meta")
                else:
                    context["error"] = data.get("message", "Search failed.")
            except Exception as e:
                context["error"] = f"Search failed: {e}"

    return render_template("search.html", **context)

# ── JSON APIs ────────────────────────────────────────────────
@app.route("/search-json", methods=["POST"])
def search_json():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON."}), 400
    q = (data.get("product") or "").strip()
    result = search_product(q)
    return jsonify(result)

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

# ── MCP AI endpoint ──────────────────────────────────────────
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

# ── Error handlers ──────────────────────────────────────────
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

# ── Run ─────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=True)
