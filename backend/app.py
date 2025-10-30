# app.py
from flask import Flask, render_template, request, jsonify
from robot_driver import search_product
from login_driver import run_login_test
import os

# Ensure Flask knows where templates/static live (inside backend/)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

MAX_CRED_LENGTH = 50  # maximum allowed length for username/password

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search", methods=["POST"])
def search():
    data = request.get_json() or {}
    product_name = data.get("product", "")
    result = search_product(product_name)
    if result.get("status") == "success":
        print(f"✅ Success! {result.get('title')} — {result.get('price')} ({result.get('meta')})")
    else:
        print(f"❌ Error: {result.get('message')}")
    return jsonify(result)

# NOTE: switched to POST so username/password can be sent safely in JSON body.
@app.route("/login-test", methods=["POST"])
def login_test():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")

    # Server-side length validation to catch overly-long inputs
    if len(username) > MAX_CRED_LENGTH or len(password) > MAX_CRED_LENGTH:
        msg = "Possible buffer overflow attempt: username or password exceeds allowed length (50)."
        print(f"❌ Security: {msg} username_len={len(username)} password_len={len(password)}")
        return jsonify({"status": "error", "message": msg}), 400

    # Proceed to run the login automation with validated inputs
    result = run_login_test(username=username, password=password)
    if result.get("status") == "success":
        print(f"✅ Login success: {result.get('message')}")
    else:
        print(f"❌ Login error: {result.get('message')}")
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
