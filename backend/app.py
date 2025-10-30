from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import os

# If you already have this, keep it; otherwise this is where we'll call it.
# from robot_driver import search_product

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")

# --- Dummy user store (replace with DB later) ---
# Store password hashes, not plain text.
USERS = {
    "mon": generate_password_hash("securemon")
}

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    # If logged in, go to search; else go to login
    if "user" in session:
        return redirect(url_for("search"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username in USERS and check_password_hash(USERS[username], password):
            session["user"] = username
            flash("Logged in successfully.", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("search"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))

@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    result = None
    error = None
    query = ""
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if not query:
            error = "Please type a product to search."
        else:
            try:
                # Integrate your Playwright logic here:
                # result = search_product(query)
                # For now, a placeholder:
                result = f"(demo) Searched for: {query}"
            except Exception as e:
                error = f"Search failed: {e}"

    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)

if __name__ == "__main__":
    # Use a non-default port if 5000 is busy
    app.run(host="0.0.0.0", port=5001, debug=True)
