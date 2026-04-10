"""CVE-2019-11324 — urllib3 certificate verification bypass.

urllib3 mishandles certain HTTPS connections when cert_reqs is set incorrectly,
allowing connections to servers with invalid or self-signed certificates without
warning.

Affected: urllib3 < 1.24.2
"""

CODE = '''\
import urllib3

def create_pool():
    """Create an HTTPS connection pool for the internal API."""
    # Disable SSL warnings for internal services
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    pool = urllib3.HTTPSConnectionPool(
        "internal-api.corp.example.com",
        port=443,
        cert_reqs="CERT_NONE",
        assert_hostname=False,
    )
    return pool

def fetch(pool, path):
    resp = pool.request("GET", path)
    return resp.data
'''

CVE = {
    "cve_id": "CVE-2019-11324",
    "severity": "critical",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "Setting cert_reqs='CERT_NONE' and assert_hostname=False disables all "
        "TLS certificate verification. A man-in-the-middle attacker can present "
        "any certificate and intercept or modify HTTPS traffic without detection."
    ),
    "fix": (
        "Remove cert_reqs='CERT_NONE' and assert_hostname=False. Use the default "
        "cert verification (cert_reqs='CERT_REQUIRED'). For internal CAs, set "
        "ca_certs to the path of the internal CA bundle."
    ),
}
