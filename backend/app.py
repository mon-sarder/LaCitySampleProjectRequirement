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

# ── App setup ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.permanent_session_lifetime = timedelta(minutes=30)
MAX_CRED_LENGTH = 50
DB_PATH = os.path.join(BASE_DIR, "users.db")

# Global agent tag
AGENT_ID = "BroncoMCP/1.0"

# ── DB setup ────────────────────────────────────────────────────────────────
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
        default_user = os.getenv("DEFAULT_USER", "admin")
        default_pass = os.getenv("DEFAULT_PASS", "admin123")
        cur.execute("SELECT 1 FROM users WHERE username = ?", (default_user,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (default_user, generate_password_hash(default_pass)),
            )
            print(f"✅ Default login added: {default_user} / {default_pass}")
        conn.commit()

init_db()

# ── Utility decorators ───────────────────────────────────────────────────────
def _too_long(x: str) -> bool:
    return x is None or len(x) > MAX_CRED_LENGTH

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return redirect(url_for("search_page") if "user" in session else url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if _too_long(username) or _too_long(password):
            flash("Credentials exceed allowed length (50 chars).", "error")
            return render_template("login.html"), 400

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, password FROM users WHERE username=?", (username,))
            user = cur.fetchone()

        if user and check_password_hash(user[1], password):
            session["user"] = username
            flash("Logged in successfully!", "success")
            return redirect(url_for("search_page"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password:
            flash("Please fill out all fields.", "error")
        elif _too_long(username) or _too_long(password):
            flash("Credentials exceed allowed length (50 chars).", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                                (username, generate_password_hash(password)))
                    conn.commit()
                flash("Account created!", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Username already exists.", "error")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

# ── Search Page ──────────────────────────────────────────────────────────────
@app.route("/search", methods=["GET", "POST"])
@login_required
def search_page():
    context = {"username": session.get("user"), "query": "", "error": None,
               "choices": None, "items": None, "picked": None}
    if request.method == "POST":
        q = request.form.get("query", "").strip()
        context["query"] = q
        if not q:
            context["error"] = "Please type a category to search."
        else:
            try:
                data = search_product(q, agent=AGENT_ID)
                if data["status"] == "choices":
                    context["choices"] = data["categories"]
                elif data["status"] == "success":
                    context["picked"] = data["category"]
                    context["items"] = data["items"]
                else:
                    context["error"] = data.get("message")
            except Exception as e:
                context["error"] = str(e)
    return render_template("search.html", **context)

# ── JSON API endpoints ───────────────────────────────────────────────────────
@app.route("/search-json", methods=["POST"])
def search_json():
    data = request.get_json(force=True)
    product_name = data.get("product", "").strip()
    result = search_product(product_name, agent=AGENT_ID)
    result["agent"] = AGENT_ID
    return jsonify(result)

@app.route("/login-test", methods=["POST"])
def login_test():
    data = request.get_json(force=True)
    username = data.get("username", "")
    password = data.get("password", "")
    if _too_long(username) or _too_long(password):
        return jsonify({"status": "error", "message": "Credentials too long."}), 400
    result = run_login_test(username=username, password=password, agent=AGENT_ID)
    result["agent"] = AGENT_ID
    return jsonify(result)

# ── MCP route ────────────────────────────────────────────────────────────────
@app.route("/mcp/run", methods=["POST"])
def mcp_run():
    from mcp_agent import run_ai_goal
    data = request.get_json(force=True)
    goal = (data.get("goal") or "").strip()
    planner = (data.get("planner") or "builtin").lower()
    headless = not bool(os.environ.get("HEADFUL") in ("1", "true", "True"))
    result = run_ai_goal(goal=goal, planner=planner, headless=headless)
    result["agent"] = AGENT_ID
    return jsonify(result)

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
