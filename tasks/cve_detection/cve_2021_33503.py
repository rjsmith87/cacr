"""CVE-2021-33503 — urllib3 ReDoS via URL authority parsing.

urllib3's URL parser uses a regex that exhibits catastrophic backtracking when
parsing a maliciously crafted URL authority component, causing a denial of
service.

Affected: urllib3 < 1.26.5
"""

CODE = '''\
import urllib3

http = urllib3.PoolManager()

def proxy_request(user_url):
    """Proxy a user-provided URL through our backend."""
    # Validate scheme
    if not user_url.startswith(("http://", "https://")):
        raise ValueError("Invalid scheme")
    resp = http.request("GET", user_url, timeout=10)
    return resp.data

# An attacker sends a crafted URL with a pathological authority string:
# proxy_request("http://" + "a" * 50000 + "@example.com/")
# The URL parser regex backtracks catastrophically, hanging the server.
'''

CVE = {
    "cve_id": "CVE-2021-33503",
    "severity": "medium",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "An attacker submits a URL with a very long authority component "
        "(e.g., 'a' * 50000 + '@host'). urllib3's URL parser regex exhibits "
        "catastrophic backtracking, causing the server thread to hang and "
        "creating a denial-of-service condition."
    ),
    "fix": (
        "Upgrade urllib3 to >= 1.26.5 which fixes the regex. Additionally, "
        "validate and truncate user-provided URLs before passing to urllib3, "
        "limiting the authority component length."
    ),
}
