# app.py
import os
import sqlite3
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

from robot_driver import search_product          # product automation (Books to Scrape)
from login_driver import run_login_test          # demo login automation (PracticeTestAutomation)

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

MAX_CRED_LENGTH = 50  # username/password hard limit (buffer-overflow style guard)
DB_PATH = os.path.join(BASE_DIR, "users.db")

@app.after_request
def set_secure_headers(resp):
    # Solid defaults; relax CSP if you later load assets from CDNs.
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp

# ── DB helpers ────────────────────────────────────────────────────────────────
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

# ── Pages (your classic flow) ─────────────────────────────────────────────────
@app.route("/")
def home():
    # If you want the single-page demo UI instead, render "index.html" here.
    if "user" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if _too_long(username) or _too_long(password):
            flash(f"Possible buffer overflow attempt: credentials exceed {MAX_CRED_LENGTH} chars.", "error")
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
            flash(f"Possible buffer overflow attempt: credentials exceed {MAX_CRED_LENGTH} chars.", "error")
            return render_template("register.html"), 400

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

@app.route("/search", methods=["GET", "POST"])
@login_required
def search_page():
    """Your protected page rendering search.html (classic, not the JSON API)."""
    result = None
    error = None
    query = ""
    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        if not query:
            error = "Please type a product to search."
        else:
            try:
                # Option A: call Playwright here synchronously
                data = search_product(query)
                if data.get("status") == "success":
                    result = f"{data['title']} — {data['price']} ({data.get('meta','')})"
                else:
                    error = data.get("message", "Search failed.")
            except Exception as e:
                error = f"Search failed: {e}"
    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)

# If you also want the single-page demo UI we built earlier:
@app.route("/demo")
def demo_index():
    return render_template("index.html")

# ── JSON APIs used by the demo index.html ─────────────────────────────────────
@app.route("/search-json", methods=["POST"])
def search_json():
    """JSON endpoint for the product automation (used by index.html)."""
    data = request.get_json() or {}
    product_name = (data.get("product") or "").strip()
    result = search_product(product_name)
    if result.get("status") == "success":
        print(f"✅ Success! {result.get('title')} — {result.get('price')} ({result.get('meta')})")
    else:
        print(f"❌ Error: {result.get('message')}")
    return jsonify(result)

@app.route("/login-test", methods=["POST"])
def login_test():
    """JSON endpoint that runs the demo login automation with length guard."""
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if _too_long(username) or _too_long(password):
        msg = f"Possible buffer overflow attempt: username or password exceeds allowed length ({MAX_CRED_LENGTH})."
        print(f"❌ Security: {msg} username_len={len(username)} password_len={len(password)}")
        return jsonify({"status": "error", "message": msg}), 400
    result = run_login_test(username=username, password=password)
    return jsonify(result)

# ── Friendly error pages ───────────────────────────────────────────
@app.errorhandler(404)
def _404(_e):
    return render_template("index.html"), 404

@app.errorhandler(500)
def _500(_e):
    return render_template("index.html"), 500

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    # Visit /demo for the SPA demo, or /login -> /search for the classic flow
    app.run(host="0.0.0.0", port=5001, debug=True)
