"""CVE-2023-32681 — Requests credential leak on redirect.

When Requests follows a redirect from an HTTPS URL to an HTTP URL, it forwards
the Authorization header to the plaintext destination, leaking credentials.

Affected: requests < 2.31.0
"""

CODE = '''\
import requests

API_TOKEN = "ghp_abc123secrettoken"

def fetch_resource(url):
    """Fetch a resource, following redirects automatically."""
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json()

# Called with a URL that 302-redirects from HTTPS to HTTP:
# fetch_resource("https://api.example.com/v1/data")
# The redirect target is http://cdn.example.com/v1/data (note: HTTP)
'''

CVE = {
    "cve_id": "CVE-2023-32681",
    "severity": "high",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "When the HTTPS endpoint redirects to an HTTP URL, the Authorization "
        "header containing the Bearer token is forwarded in plaintext over the "
        "unencrypted connection. A network attacker can intercept the token."
    ),
    "fix": (
        "Upgrade requests to >= 2.31.0, which strips the Authorization header "
        "on HTTPS-to-HTTP redirects. Alternatively, disable redirects "
        "(allow_redirects=False) and handle them manually with scheme checking."
    ),
}
