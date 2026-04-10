"""CVE-2023-25577 — Werkzeug multipart form data DoS.

Werkzeug's multipart parser consumes excessive memory when processing
large file uploads with specially crafted content-disposition headers,
causing denial of service.

Affected: Werkzeug < 2.2.3
"""

CODE = '''\
from flask import Flask, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

@app.route("/upload", methods=["POST"])
def upload():
    """Accept file uploads from users."""
    f = request.files.get("document")
    if f is None:
        return "No file", 400
    content = f.read()
    # process content...
    return f"Received {len(content)} bytes", 200

# Even with MAX_CONTENT_LENGTH set, a crafted multipart request with
# many parts and specific content-disposition values can cause Werkzeug's
# parser to allocate excessive memory before the size check triggers.
'''

CVE = {
    "cve_id": "CVE-2023-25577",
    "severity": "high",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "An attacker sends a multipart/form-data request with many parts and "
        "crafted content-disposition headers. Werkzeug's parser allocates memory "
        "for each part before checking MAX_CONTENT_LENGTH, allowing memory "
        "exhaustion and denial of service."
    ),
    "fix": (
        "Upgrade Werkzeug to >= 2.2.3, which limits memory allocation during "
        "multipart parsing. Also consider adding request size limits at the "
        "reverse proxy layer (nginx/CloudFlare)."
    ),
}
