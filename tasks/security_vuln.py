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
    # =========================================================================
    # EASY (10) -- textbook OWASP patterns
    # =========================================================================

    # --- sql_injection (easy 1) ---
    {
        "complexity": "easy",
        "code": '''\
def get_user(conn, username):
    query = f"SELECT * FROM users WHERE name = '{username}'"
    return conn.execute(query).fetchone()
''',
        "label": "sql_injection",
    },

    # --- sql_injection (easy 2) ---
    {
        "complexity": "easy",
        "code": '''\
import sqlite3

def login(username, password):
    conn = sqlite3.connect("app.db")
    sql = "SELECT * FROM users WHERE user='" + username + "' AND pass='" + password + "'"
    return conn.execute(sql).fetchone()
''',
        "label": "sql_injection",
    },

    # --- xss (easy 1) ---
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

    # --- xss (easy 2) ---
    {
        "complexity": "easy",
        "code": '''\
from flask import request

@app.route("/search")
def search():
    q = request.args.get("q", "")
    return "<p>You searched for: " + q + "</p>"
''',
        "label": "xss",
    },

    # --- path_traversal (easy 1) ---
    {
        "complexity": "easy",
        "code": '''\
from flask import request

@app.route("/read")
def read_file():
    filename = request.args.get("file")
    with open("/var/data/" + filename) as f:
        return f.read()
''',
        "label": "path_traversal",
    },

    # --- path_traversal (easy 2) ---
    {
        "complexity": "easy",
        "code": '''\
from flask import request, send_file
import os

@app.route("/download")
def download():
    path = os.path.join("/uploads", request.args["name"])
    return send_file(path)
''',
        "label": "path_traversal",
    },

    # --- hardcoded_secret (easy 1) ---
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

    # --- hardcoded_secret (easy 2) ---
    {
        "complexity": "easy",
        "code": '''\
import psycopg2

def get_connection():
    return psycopg2.connect(
        host="prod-db.example.com",
        user="admin",
        password="P@ssw0rd!2025",
        dbname="production",
    )
''',
        "label": "hardcoded_secret",
    },

    # --- insecure_deserialization (easy 1) ---
    {
        "complexity": "easy",
        "code": '''\
import pickle
from flask import request

@app.route("/upload", methods=["POST"])
def upload():
    obj = pickle.loads(request.data)
    return str(obj)
''',
        "label": "insecure_deserialization",
    },

    # --- insecure_deserialization (easy 2) ---
    {
        "complexity": "easy",
        "code": '''\
import pickle

def load_model(path):
    with open(path, "rb") as f:
        model = pickle.load(f)
    return model
''',
        "label": "insecure_deserialization",
    },

    # =========================================================================
    # MEDIUM (10) -- real-world, vulnerability one layer removed
    # =========================================================================

    # --- sql_injection (medium 1) ---
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

    # --- sql_injection (medium 2) ---
    {
        "complexity": "medium",
        "code": '''\
from flask import request
import psycopg2

@app.route("/users")
def list_users():
    sort_col = request.args.get("sort", "id")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(f"SELECT id, name, email FROM users ORDER BY {sort_col}")
    return jsonify(cur.fetchall())
''',
        "label": "sql_injection",
    },

    # --- xss (medium 1) -- stored XSS via database ---
    {
        "complexity": "medium",
        "code": '''\
from flask import request
import subprocess

@app.route("/search")
def search():
    q = request.args.get("q", "")
    results = db.execute("SELECT title FROM docs WHERE id = ?", (q,)).fetchall()
    html = "<ul>" + "".join(f"<li>{r[0]}</li>" for r in results) + "</ul>"
    return html
''',
        "label": "xss",
    },

    # --- xss (medium 2) -- Jinja2 markup_safe bypass ---
    {
        "complexity": "medium",
        "code": '''\
from flask import request
from markupsafe import Markup

@app.route("/preview")
def preview():
    user_html = request.form.get("body", "")
    safe = Markup("<div class='preview'>") + Markup(user_html) + Markup("</div>")
    return safe
''',
        "label": "xss",
    },

    # --- path_traversal (medium 1) ---
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

    # --- path_traversal (medium 2) -- zip extraction ---
    {
        "complexity": "medium",
        "code": '''\
import zipfile, os
from flask import request

@app.route("/import", methods=["POST"])
def import_archive():
    zf = zipfile.ZipFile(request.files["archive"])
    for name in zf.namelist():
        dest = os.path.join("/var/data/imports", name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as out:
            out.write(zf.read(name))
    return "imported"
''',
        "label": "path_traversal",
    },

    # --- hardcoded_secret (medium 1) ---
    {
        "complexity": "medium",
        "code": '''\
from flask import Flask

app = Flask(__name__)
app.config["SECRET_KEY"] = "fe230b4a9f1c84d67e"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
''',
        "label": "hardcoded_secret",
    },

    # --- hardcoded_secret (medium 2) -- JWT signing ---
    {
        "complexity": "medium",
        "code": '''\
import jwt
from datetime import datetime, timedelta

SIGNING_KEY = "my-jwt-secret-2025"

def create_token(user_id):
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    return jwt.encode(payload, SIGNING_KEY, algorithm="HS256")
''',
        "label": "hardcoded_secret",
    },

    # --- insecure_deserialization (medium 1) -- pickle via base64 ---
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

    # --- insecure_deserialization (medium 2) -- yaml.load ---
    {
        "complexity": "medium",
        "code": '''\
import yaml
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/settings")
async def update_settings(request: Request):
    body = await request.body()
    config = yaml.load(body, Loader=yaml.Loader)
    return {"status": "applied", "keys": list(config.keys())}
''',
        "label": "insecure_deserialization",
    },

    # =========================================================================
    # HARD (10) -- obfuscated / multi-layer / requires reasoning across 5+ lines
    # =========================================================================

    # --- sql_injection (hard 1) -- table name is user-controlled, value is parameterised ---
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

    # --- sql_injection (hard 2) -- "sanitize" that misses edge cases ---
    {
        "complexity": "hard",
        "code": '''\
import psycopg2

def safe_query(conn, user_input):
    sanitized = user_input.replace("'", "''")
    # Developer believes double-quoting neutralises the input
    q = f"""SELECT id, body FROM comments
            WHERE author = E'{sanitized}'
            ORDER BY created_at DESC"""
    cur = conn.cursor()
    cur.execute(q)
    return cur.fetchall()
''',
        "label": "sql_injection",
    },

    # --- xss (hard 1) -- render_template_string with user-controlled path param ---
    {
        "complexity": "hard",
        "code": '''\
from flask import request, render_template_string

THEMES = {"dark": "#111", "light": "#fff"}

@app.route("/profile/<username>")
def profile(username):
    theme = THEMES.get(request.args.get("theme", "light"), "#fff")
    tmpl = (
        "<html><head><style>body{background:" + theme + "}</style></head>"
        "<body><h1>Profile: " + username + "</h1></body></html>"
    )
    return render_template_string(tmpl)
''',
        "label": "xss",
    },

    # --- xss (hard 2) -- stored XSS via Markdown rendering ---
    {
        "complexity": "hard",
        "code": '''\
import markdown
from flask import request

@app.route("/article", methods=["POST"])
def create_article():
    raw_md = request.form["body"]
    rendered = markdown.markdown(raw_md, extensions=["extra"])
    db.execute(
        "INSERT INTO articles (html) VALUES (?)", (rendered,)
    )
    return "saved"

@app.route("/article/<int:aid>")
def view_article(aid):
    row = db.execute("SELECT html FROM articles WHERE id = ?", (aid,)).fetchone()
    return f"<div class='article'>{row[0]}</div>"
''',
        "label": "xss",
    },

    # --- path_traversal (hard 1) -- lstrip("/") doesn't stop ../ ---
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

    # --- path_traversal (hard 2) -- date validation that doesn't block traversal ---
    {
        "complexity": "hard",
        "code": '''\
from flask import request
import os

@app.route("/logs")
def view_log():
    day = request.args.get("day", "2026-01-01")
    # sanitise: only allow YYYY-MM-DD format
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        path = os.path.join("/var/log/app", day + ".log")
        return open(path).read()
    return "bad date", 400
''',
        "label": "path_traversal",
    },

    # --- hardcoded_secret (hard 1) -- default fallback values in env lookup ---
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

    # --- hardcoded_secret (hard 2) -- HMAC secret buried in helper module ---
    {
        "complexity": "hard",
        "code": '''\
import hmac, hashlib, os

_FALLBACK = b"xK9#mP2$vL5nQ8wR"

def _get_key():
    val = os.environ.get("HMAC_KEY")
    return val.encode() if val else _FALLBACK

def verify_webhook(payload: bytes, signature: str) -> bool:
    key = _get_key()
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
''',
        "label": "hardcoded_secret",
    },

    # --- insecure_deserialization (hard 1) -- eval hidden behind decode ---
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

    # --- insecure_deserialization (hard 2) -- shelve with user-controlled path ---
    {
        "complexity": "hard",
        "code": '''\
import shelve
from fastapi import FastAPI, Query

app = FastAPI()

CACHE_DIR = "/tmp/app_cache"

def _load_shelf(ns: str, key: str):
    shelf_path = f"{CACHE_DIR}/{ns}"
    with shelve.open(shelf_path) as db:
        return db.get(key)

@app.get("/cache")
def read_cache(ns: str = Query(...), key: str = Query(...)):
    val = _load_shelf(ns, key)
    if val is None:
        return {"error": "miss"}
    return {"value": val}
''',
        "label": "insecure_deserialization",
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
