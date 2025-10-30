from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

# Import your automation/search logic if needed
# from robot_driver import search_product

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")

# -------------------------------
# In-memory user store (for demo)
# -------------------------------
# In production, replace this with a database (SQLite, etc.)
USERS = {
    "mon": generate_password_hash("supersecurepw")
}

# -------------------------------
# Login required decorator
# -------------------------------
def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

# -------------------------------
# Routes
# -------------------------------

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("search"))
    return redirect(url_for("login"))

# -------------------------------
# LOGIN
# -------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if username in USERS and check_password_hash(USERS[username], password):
            session["user"] = username
            flash("Logged in successfully!", "success")
            return redirect(url_for("search"))
        flash("Invalid username or password.", "error")

    return render_template("login.html")

# -------------------------------
# REGISTER
# -------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm = request.form["confirm"]

        if not username or not password:
            flash("Please fill out all fields.", "error")
        elif username in USERS:
            flash("Username already exists. Try logging in.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            USERS[username] = generate_password_hash(password)
            session["user"] = username
            flash("Account created successfully!", "success")
            return redirect(url_for("search"))

    return render_template("register.html")

# -------------------------------
# LOGOUT
# -------------------------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

# -------------------------------
# SEARCH (protected)
# -------------------------------
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
                # Replace this placeholder with your robot_driver search call:
                # result = search_product(query)
                result = f"(demo) Successfully searched for '{query}'"
            except Exception as e:
                error = f"Search failed: {e}"

    return render_template(
        "search.html",
        username=session.get("user"),
        result=result,
        error=error,
        query=query,
    )

# -------------------------------
# Run the Flask app
# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
