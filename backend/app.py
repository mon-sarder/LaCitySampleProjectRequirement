# app.py
from flask import Flask, render_template, request, jsonify
from robot_driver import search_product
import os

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)

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
