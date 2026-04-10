"""CVE-2018-18074 — Requests HTTP auth credential leak on redirect.

Requests leaks HTTP Basic/Digest authentication credentials when following
redirects from a host that requires auth to a different host.

Affected: requests < 2.20.0
"""

CODE = '''\
import requests
from requests.auth import HTTPBasicAuth

def sync_data(source_url, dest_url):
    """Pull data from source API, which may redirect to a partner API."""
    auth = HTTPBasicAuth("service_account", "s3cretP@ss!")
    resp = requests.get(source_url, auth=auth, allow_redirects=True)
    resp.raise_for_status()
    return resp.content

# source_url may 302 to a completely different host (dest_url)
# The BasicAuth credentials are forwarded to the redirected host
'''

CVE = {
    "cve_id": "CVE-2018-18074",
    "severity": "high",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "When source_url redirects to a different host, the HTTP Basic Auth "
        "credentials (username and password) are included in the request to "
        "the new host, leaking them to a third party."
    ),
    "fix": (
        "Upgrade requests to >= 2.20.0, which strips auth credentials on "
        "cross-host redirects. Or disable redirects and re-issue the request "
        "manually without auth to the new host."
    ),
}
