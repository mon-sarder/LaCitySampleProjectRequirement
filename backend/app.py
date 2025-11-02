# app.py
import os
import sqlite3
import traceback
from datetime import timedelta, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import BadRequest
from jinja2 import TemplateNotFound

# --- External robot driver (Playwright) ---
# Expected functions:
#   - search_product(query: str) -> dict (status, title, price, meta, category, etc.)
#   - Optional: list_categories() -> list[str]
try:
    from robot_driver import search_product  # Core bot used by /search-json and /api/run
except Exception:
    search_product = None

try:
    # Optional; if not present we'll use a small fallback list
    from robot_driver import list_categories as rd_list_categories
except Exception:
    rd_list_categories = None


# ──────────────────────────────────────────────────────────────────────────────
# App & configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# Security / sessions
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB request cap
app.permanent_session_lifetime = timedelta(minutes=30)  # session timeout

# API key for JSON/MCP endpoints
API_KEY = os.environ.get("API_KEY", "secret123")

# Database path
DB_PATH = os.path.join(BASE_DIR, "users.db")

# Lightweight metrics
START_TIME = datetime.utcnow()
REQUEST_COUNT = {"api": 0, "ui": 0}


# ──────────────────────────────────────────────────────────────────────────────
# Tiny metrics helper
# ──────────────────────────────────────────────────────────────────────────────
def bump(kind: str):
    if kind in REQUEST_COUNT:
        REQUEST_COUNT[kind] += 1


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────
def init_db():
    """Create the users table if it doesn’t exist."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """
        )
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
            cur.execute(
                "SELECT username, password FROM users WHERE username = ?",
                (username,),
            )
            return cur.fetchone()

    return _safe_query(_q)


def add_user(username: str, password_hash: str):
    def _q():
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password_hash),
            )
            conn.commit()
            return True

    return _safe_query(_q)


init_db()


# ──────────────────────────────────────────────────────────────────────────────
# Categories cache (safe fallback)
# ──────────────────────────────────────────────────────────────────────────────
def _fallback_categories():
    # A compact, sensible subset; MCP just needs valid JSON
    return [
        "Travel",
        "Mystery",
        "Historical Fiction",
        "Sequential Art",
        "Classics",
        "Philosophy",
        "Romance",
        "Womens Fiction",
        "Fiction",
        "Childrens",
    ]


def _fetch_categories():
    """Try robot_driver.list_categories(); fall back to a stable built-in list."""
    if callable(rd_list_categories):
        try:
            cats = rd_list_categories()
            if isinstance(cats, (list, tuple)) and cats:
                return sorted({str(c).strip() for c in cats if str(c).strip()})
        except Exception as e:
            print(f"⚠️ list_categories() failed: {e}")
    return _fallback_categories()


CATEGORIES = _fetch_categories()


# ──────────────────────────────────────────────────────────────────────────────
# Simple API-key check for JSON/MCP endpoints
# ──────────────────────────────────────────────────────────────────────────────
def require_api_key():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Security headers
# ──────────────────────────────────────────────────────────────────────────────
@app.after_request
def set_secure_headers(resp):
    # Good defaults; relax CSP if using external CDNs
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # Allow scripts/styles from self only; images from self and data URLs
    resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp


@app.before_request
def make_session_permanent():
    session.permanent = True


# ──────────────────────────────────────────────────────────────────────────────
# Auth gate: make UI pages require login, but allow API/JSON routes
# ──────────────────────────────────────────────────────────────────────────────
PUBLIC_PATHS = {
    "/login",
    "/register",
    "/api/health",       # keep open for easy health checks
    "/categories.json",  # API-key protected in the route
    "/search-json",      # API-key protected in the route
    "/api/run",          # API-key protected in the route
    "/api/metrics",      # API-key protected in the route
}

@app.before_request
def auth_gate():
    """
    Require login for UI pages, while allowing JSON/API endpoints (and static)
    to be accessed without a session. The JSON/API routes still require an API key
    at the route level (see require_api_key()).
    """
    path = request.path or "/"

    # Count UI/API requests for metrics
    if path.startswith("/api/") or path.endswith(".json"):
        bump("api")
    else:
        bump("ui")

    # Always allow static files
    if path.startswith("/static/"):
        return

    # Allow JSON/API routes to pass (they’ll enforce API key in-route)
    if path in PUBLIC_PATHS or path.startswith("/api/"):
        return

    # UI pages require login
    if "username" not in session and request.endpoint not in ("login", "register", "static"):
        return redirect(url_for("login", next=path))


# ──────────────────────────────────────────────────────────────────────────────
# Login-required decorator (used for the search UI page)
# ──────────────────────────────────────────────────────────────────────────────
def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────────────────────────────────────
# Routes: UI pages
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    if "username" in session:
        return redirect(url_for("search_page"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = get_user(username)
        if user and check_password_hash(user[1], password):
            session["username"] = username
            flash("Logged in successfully!", "success")
            return redirect(url_for("search_page"))
        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

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
            session["username"] = username
            flash("Account created successfully!", "success")
            return redirect(url_for("search_page"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.pop("username", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


@app.route("/search", methods=["GET", "POST"])
@login_required
def search_page():
    """
    Protected UI page: renders 'search.html'. The actual bot call happens via /search-json.
    """
    result = None
    error = None
    query = ""

    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        if not query:
            error = "Please type a product to search."
        else:
            try:
                if not callable(search_product):
                    raise RuntimeError("search_product not available")
                data = search_product(query)
                if isinstance(data, dict) and data.get("status") == "success":
                    result = f"{data.get('title')} — {data.get('price')} ({data.get('meta','')})"
                else:
                    error = (data.get("message") if isinstance(data, dict) else None) or "Search failed."
            except Exception as e:
                error = f"Search failed: {e}"

    return render_template(
        "search.html",
        username=session.get("username"),
        result=result,
        error=error,
        query=query,
    )


# ──────────────────────────────────────────────────────────────────────────────
# JSON / MCP Endpoints (API-key protected)
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/categories.json", methods=["GET"])
def categories_json():
    # API-key protection
    unauthorized = require_api_key()
    if unauthorized:
        return unauthorized

    return jsonify(
        {
            "status": "success",
            "agent": "BroncoMCP/1.0",
            "categories": sorted(CATEGORIES),
        }
    )


@app.route("/search-json", methods=["POST"])
def search_json():
    # API-key protection
    unauthorized = require_api_key()
    if unauthorized:
        return unauthorized

    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({"status": "error", "message": "Invalid JSON format."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    product_name = (data.get("product") or data.get("query") or "").strip()
    if not product_name:
        return jsonify({"status": "error", "message": "Missing 'product' or 'query'."}), 400

    if not callable(search_product):
        return jsonify({"status": "error", "message": "Search engine unavailable"}), 503

    try:
        result = search_product(product_name)
        if not isinstance(result, dict):
            return jsonify({"status": "error", "message": "Unexpected driver result"}), 500
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Search failed: {e}"}), 500


@app.route("/api/run", methods=["POST"])
def api_run():
    # API-key protection
    unauthorized = require_api_key()
    if unauthorized:
        return unauthorized

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

    goal = (payload.get("goal") or "").strip()
    if not goal:
        return jsonify({"status": "error", "message": "Please provide a non-empty 'goal'."}), 400

    # Very simple planner: interpret the goal as a search
    try:
        if not callable(search_product):
            raise RuntimeError("search_product not available")
        data = search_product(goal)
        return jsonify(
            {
                "status": "success" if data.get("status") == "success" else "error",
                "agent": "BroncoMCP/1.0",
                "goal": goal,
                "result": data,
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "agent": "BroncoMCP/1.0", "message": str(e)}), 500


@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    # API-key protection
    unauthorized = require_api_key()
    if unauthorized:
        return unauthorized

    uptime = (datetime.utcnow() - START_TIME).total_seconds()
    return jsonify(
        {
            "status": "success",
            "agent": "BroncoMCP/1.0",
            "uptime_seconds": uptime,
            "requests": REQUEST_COUNT,
        }
    )


@app.route("/api/health", methods=["GET"])
def api_health():
    # Leave health open (no key) so deploy checks are easy
    try:
        ok = bool(callable(search_product))
        return jsonify(
            {
                "status": "ok" if ok else "degraded",
                "agent": "BroncoMCP/1.0",
                "has_search": ok,
                "categories_cached": len(CATEGORIES),
                "time": datetime.utcnow().isoformat() + "Z",
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
# Error pages
# ──────────────────────────────────────────────────────────────────────────────
@app.errorhandler(404)
def _404(_e):
    try:
        return render_template("index.html"), 404
    except TemplateNotFound:
        return jsonify({"status": "error", "message": "Not found"}), 404


@app.errorhandler(500)
def _500(_e):
    try:
        return render_template("index.html"), 500
    except TemplateNotFound:
        return jsonify({"status": "error", "message": "Server error"}), 500


# ──────────────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    # Default admin seeding (optional)
    if not get_user("admin"):
        try:
            add_user("admin", generate_password_hash("admin123"))
            print("Seeded default admin: admin / admin123")
        except Exception:
            pass

    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
