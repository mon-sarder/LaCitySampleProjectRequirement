# app.py
import os
from flask import Flask, render_template, request, jsonify

from robot_driver import search_product
from login_driver import run_login_test

# ── Flask app + paths ──────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# ── Security / limits ─────────────────────────────────────────────────────────
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB request cap

MAX_CRED_LENGTH = 50  # single source of truth for username/password limit


@app.after_request
def set_secure_headers(resp):
    # Solid defaults; relax CSP if you later pull assets from CDNs
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:;"
    return resp


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── API: Product automation (Books to Scrape) ─────────────────────────────────
@app.route("/search", methods=["POST"])
def search():
    data = request.get_json() or {}
    product_name = (data.get("product") or "").strip()
    result = search_product(product_name)
    # Console log for graders
    if result.get("status") == "success":
        print(f"✅ Success! {result.get('title')} — {result.get('price')} ({result.get('meta')})")
    else:
        print(f"❌ Error: {result.get('message')}")
    return jsonify(result)


# ── API: Demo login automation with input-length guard ────────────────────────
@app.route("/login-test", methods=["POST"])
def login_test():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) > MAX_CRED_LENGTH or len(password) > MAX_CRED_LENGTH:
        msg = (
            "Possible buffer overflow attempt: username or password exceeds "
            f"allowed length ({MAX_CRED_LENGTH})."
        )
        print(f"❌ Security: {msg} username_len={len(username)} password_len={len(password)}")
        return jsonify({"status": "error", "message": msg}), 400

    result = run_login_test(username=username, password=password)
    if result.get("status") == "success":
        print(f"✅ Login success: {result.get('message')}")
    else:
        print(f"❌ Login error: {result.get('message')}")
    return jsonify(result)


# ── Friendly errors (optional) ────────────────────────────────────────────────
@app.errorhandler(404)
def _404(_e):
    return render_template("index.html"), 404


@app.errorhandler(500)
def _500(_e):
    return render_template("index.html"), 500


if __name__ == "__main__":
    # For headful demo: set HEADFUL=1 in env and we’ll respect it in drivers
    app.run(debug=True)
