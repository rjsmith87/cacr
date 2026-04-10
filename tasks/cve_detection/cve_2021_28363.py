"""CVE-2021-28363 — urllib3 HTTPS proxy MITM.

urllib3 does not verify the TLS certificate of the HTTPS proxy itself,
allowing a man-in-the-middle to intercept the proxy tunnel setup.

Affected: urllib3 < 1.26.4
"""

CODE = '''\
import urllib3

def create_proxy_pool():
    """Connect to an external API through a corporate HTTPS proxy."""
    proxy = urllib3.ProxyManager(
        "https://proxy.corp.example.com:8443",
        proxy_headers={"Proxy-Authorization": "Basic dXNlcjpwYXNz"},
    )
    resp = proxy.request("GET", "https://api.external.com/data")
    return resp.data

# The HTTPS proxy's certificate is not verified by urllib3.
# An attacker on the network can impersonate the proxy, intercept the
# CONNECT tunnel, and read/modify all traffic including credentials.
'''

CVE = {
    "cve_id": "CVE-2021-28363",
    "severity": "high",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "urllib3's ProxyManager does not verify the TLS certificate of the HTTPS "
        "proxy. A network attacker can present a forged certificate for the proxy, "
        "intercept the CONNECT tunnel, and read or modify all proxied traffic "
        "including authentication headers."
    ),
    "fix": (
        "Upgrade urllib3 to >= 1.26.4, which verifies the HTTPS proxy certificate. "
        "Alternatively, use a proxy CA bundle via proxy_ssl_context."
    ),
}
