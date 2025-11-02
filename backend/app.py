from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import difflib
import time
import os

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# --- Simple mock database ---------------------------------------------------
users = {'admin': 'password123'}
CATEGORIES = [
    "Travel", "Mystery", "Historical Fiction", "Sequential Art", "Classics",
    "Philosophy", "Romance", "Womens Fiction", "Fiction", "Childrens",
    "Religion", "Nonfiction", "Music", "Science", "Sports",
    "Business", "Self Help", "Fantasy", "Science Fiction", "Poetry",
    "Humor", "Psychology", "Cooking", "Art", "Drama",
    "Comics", "Politics", "Technology", "Health", "History",
    "Education", "Nature", "Biography", "Adventure", "Photography",
    "Crafts", "Economics", "Parenting", "Philanthropy", "Horror",
    "Law", "Sociology", "Mathematics", "Anthropology", "Linguistics",
    "Environment", "Astronomy", "Animals", "Gardening", "Design"
]

# --- Utility: search function -----------------------------------------------
def search_products(category_query):
    results = []
    for c in CATEGORIES:
        if category_query.lower() in c.lower():
            results.append({
                "category": c,
                "items": [
                    {"name": f"{c} Item 1", "price": "$10"},
                    {"name": f"{c} Item 2", "price": "$15"},
                    {"name": f"{c} Item 3", "price": "$20"}
                ]
            })
    return results


# --- Routes: login/logout ---------------------------------------------------
@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('search_page'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username] == password:
            session['username'] = username
            return redirect(url_for('search_page'))
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


# --- Main Search Page -------------------------------------------------------
@app.route('/search', methods=['GET', 'POST'])
def search_page():
    if 'username' not in session:
        return redirect(url_for('login'))

    results = []
    message = None

    if request.method == 'POST':
        category_query = request.form.get('category', '')
        matches = difflib.get_close_matches(category_query, CATEGORIES, n=1, cutoff=0.7)

        if matches:
            results = search_products(matches[0])
        else:
            message = "No close category match. Pick one of the available categories."

    return render_template(
        'index.html',
        username=session['username'],
        categories=CATEGORIES,
        results=results,
        message=message
    )


# --- MCP endpoints ----------------------------------------------------------
@app.route('/search-json', methods=['POST'])
def search_json():
    data = request.get_json(force=True)
    query = data.get('product', '')
    headless = data.get('headless', True)

    # return items for close matches, or entire category list if no match
    results = search_products(query)
    if not results:
        results = [{"category": c, "items": []} for c in CATEGORIES]

    return jsonify({
        "status": "success",
        "agent": "BroncoMCP/1.0",
        "items": results,
        "meta": {"query": query, "count": len(results)},
    })


@app.route('/api/run', methods=['POST'])
def api_run():
    try:
        data = request.get_json(force=True)
        intent = data.get('intent', 'search_product')
        query = data.get('query', '')
        if intent == 'search_product':
            results = search_products(query)
            return jsonify({
                "status": "success",
                "agent": "BroncoMCP/1.0",
                "results": results,
            })
        else:
            return jsonify({"status": "error", "message": "Unknown intent"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/metrics', methods=['POST'])
def api_metrics():
    try:
        data = request.get_json(force=True)
        print(f"[METRIC] {json.dumps(data, indent=2)}")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --- FIXED: Categories JSON endpoint for MCP list_categories ----------------
@app.route('/categories.json', methods=['GET'])
def categories_json():
    """
    Returns a clean JSON list so MCP list_categories() parses correctly.
    """
    return jsonify({
        "status": "success",
        "agent": "BroncoMCP/1.0",
        "categories": sorted(CATEGORIES)
    })


# --- Health check -----------------------------------------------------------
@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({"status": "ok", "agent": "BroncoMCP/1.0", "uptime_s": time.time()})


# --- Launch -----------------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
