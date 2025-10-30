from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")

# In-memory user store (use a real DB later)
USERS = {
    "mon": generate_password_hash("supersecurepw")
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
    if "user" in session:
        return redirect(url_for("search"))
    return redirect(url_for("login"))

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
            # Integrate your robot_driver here if desired
            result = f"(demo) searched for '{query}'"
    return render_template("search.html", username=session.get("user"), result=result, error=error, query=query)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
