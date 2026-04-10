"""CVE-2023-30861 — Flask session cookie disclosure.

Responses cached with Vary: Cookie can leak one user's session to another
behind a shared proxy/cache when Cache-Control: public is set on a
session-dependent response.

Affected: Flask < 2.3.2
"""

CODE = '''\
from flask import Flask, session, jsonify, request

app = Flask(__name__)
app.secret_key = "dev-secret-key"

@app.route("/profile")
def profile():
    session["visited"] = True
    resp = jsonify({"user": session.get("user_id"), "role": session.get("role")})
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp

@app.route("/login", methods=["POST"])
def login():
    session["user_id"] = request.form["user"]
    session["role"] = "admin" if request.form["user"] == "admin" else "viewer"
    return "OK"
'''

CVE = {
    "cve_id": "CVE-2023-30861",
    "severity": "high",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "A shared HTTP cache (CDN/proxy) serves a cached response that includes "
        "Set-Cookie with one user's session to a different user. The /profile "
        "endpoint sets Cache-Control: public on a response that depends on session "
        "state, causing session data leakage across users."
    ),
    "fix": (
        "Remove 'Cache-Control: public' from responses that use session data, or "
        "upgrade Flask to >= 2.3.2 which adds Vary: Cookie automatically and "
        "prevents caching of session-dependent responses."
    ),
}
