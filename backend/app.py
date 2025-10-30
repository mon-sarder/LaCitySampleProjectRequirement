# app.py
from flask import Flask, render_template, request, jsonify
from robot_driver import search_product

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    product_name = data.get("product", "")
    result = search_product(product_name)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
