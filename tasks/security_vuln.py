"""Security vulnerability identification task.

Given a code snippet, identify the vulnerability type.
Categories: sql_injection, xss, path_traversal, hardcoded_secret, insecure_deserialization.
Score is exact match (case-insensitive, stripped).
"""

from typing import Any

from tasks.base import Task


VULN_TYPES = [
    "sql_injection", "xss", "path_traversal",
    "hardcoded_secret", "insecure_deserialization",
]

EXAMPLES = [
    # --- easy ---
    {
        "complexity": "easy",
        "code": '''\
def get_user(conn, username):
    query = f"SELECT * FROM users WHERE name = '{username}'"
    return conn.execute(query).fetchone()
''',
        "label": "sql_injection",
    },
    {
        "complexity": "easy",
        "code": '''\
from flask import request

@app.route("/greet")
def greet():
    name = request.args.get("name", "")
    return f"<h1>Hello, {name}!</h1>"
''',
        "label": "xss",
    },
    {
        "complexity": "easy",
        "code": '''\
API_KEY = "sk-live-4f3c2b1a0987654321abcdef"

def call_api(endpoint):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    return requests.get(endpoint, headers=headers)
''',
        "label": "hardcoded_secret",
    },
    # --- medium ---
    {
        "complexity": "medium",
        "code": '''\
from flask import request, send_from_directory

@app.route("/download")
def download():
    filename = request.args.get("file")
    return send_from_directory("/var/data", filename)
''',
        "label": "path_traversal",
    },
    {
        "complexity": "medium",
        "code": '''\
import pickle, base64
from flask import request

@app.route("/load", methods=["POST"])
def load_session():
    data = base64.b64decode(request.form["session"])
    return pickle.loads(data)
''',
        "label": "insecure_deserialization",
    },
    {
        "complexity": "medium",
        "code": '''\
from flask import request
import subprocess

@app.route("/search")
def search():
    q = request.args.get("q", "")
    # Uses parameterised query but renders result unsafely
    results = db.execute("SELECT title FROM docs WHERE id = ?", (q,)).fetchall()
    html = "<ul>" + "".join(f"<li>{r[0]}</li>" for r in results) + "</ul>"
    return html
''',
        "label": "xss",
    },
    {
        "complexity": "medium",
        "code": '''\
import sqlite3

def search_products(name, category):
    conn = sqlite3.connect("shop.db")
    query = "SELECT * FROM products WHERE name LIKE '%" + name + "%'"
    if category:
        query += f" AND category = '{category}'"
    return conn.execute(query).fetchall()
''',
        "label": "sql_injection",
    },
    # --- hard ---
    {
        "complexity": "hard",
        "code": '''\
import os

UPLOAD_DIR = "/var/uploads"

def save_upload(filename, content):
    # Strips leading slashes but not ../ sequences
    clean = filename.lstrip("/")
    path = os.path.join(UPLOAD_DIR, clean)
    with open(path, "wb") as f:
        f.write(content)
''',
        "label": "path_traversal",
    },
    {
        "complexity": "hard",
        "code": '''\
import yaml
from flask import request

@app.route("/config", methods=["POST"])
def update_config():
    config = yaml.load(request.data, Loader=yaml.Loader)
    apply_settings(config)
    return "OK"
''',
        "label": "insecure_deserialization",
    },
    {
        "complexity": "hard",
        "code": '''\
import os

DB_PASSWORD = os.environ.get("DB_PASS", "changeme123")
ENCRYPTION_KEY = os.environ.get("ENC_KEY", "0" * 32)

def get_connection():
    return psycopg2.connect(
        host="db.internal",
        password=DB_PASSWORD,
    )
''',
        "label": "hardcoded_secret",
    },
    # --- 5 additional hard examples ---
    {
        "complexity": "hard",
        "code": '''\
from flask import request, render_template_string

@app.route("/profile/<username>")
def profile(username):
    tmpl = f"<html><body>Welcome back, {username}!</body></html>"
    return render_template_string(tmpl)
''',
        "label": "xss",
    },
    {
        "complexity": "hard",
        "code": '''\
import json, base64

def restore_checkpoint(b64data):
    raw = base64.b64decode(b64data)
    obj = eval(raw.decode("utf-8"))
    return obj
''',
        "label": "insecure_deserialization",
    },
    {
        "complexity": "hard",
        "code": '''\
from flask import request
import os

@app.route("/logs")
def view_log():
    day = request.args.get("day", "2026-01-01")
    # sanitise: only allow YYYY-MM-DD
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        path = os.path.join("/var/log/app", day + ".log")
        return open(path).read()
    return "bad date", 400
''',
        "label": "path_traversal",
    },
    {
        "complexity": "hard",
        "code": '''\
from django.db import connection

def audit_search(tbl, col, val):
    allowed_tables = ["users", "orders", "products"]
    if tbl not in allowed_tables:
        raise ValueError("bad table")
    sql = f"SELECT * FROM {tbl} WHERE {col} = %s"
    with connection.cursor() as c:
        c.execute(sql, [val])
        return c.fetchall()
''',
        "label": "sql_injection",
    },
    {
        "complexity": "hard",
        "code": '''\
import hmac, hashlib

SECRET = b"supersecret"

def verify(msg, sig):
    expected = hmac.new(SECRET, msg.encode(), hashlib.sha256).hexdigest()
    return sig == expected

# Also: SECRET is hardcoded in source
''',
        "label": "hardcoded_secret",
    },
]


class SecurityVuln(Task):
    family = "classification"
    complexity = "mixed"
    threshold = 0.6

    def examples(self) -> list[dict[str, Any]]:
        return EXAMPLES

    def prompt(self, example: dict[str, Any]) -> str:
        cats = ", ".join(VULN_TYPES)
        return (
            "Identify the security vulnerability in the following code.\n"
            f"Vulnerability types: {cats}\n"
            "Respond with ONLY the vulnerability type, nothing else.\n\n"
            f"```python\n{example['code']}```\n"
            "Vulnerability type:"
        )

    def eval(self, example: dict[str, Any], output: str) -> float:
        first = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
        guess = first.lower().strip(" .,:;\"'`*")
        return 1.0 if guess == example["label"] else 0.0
