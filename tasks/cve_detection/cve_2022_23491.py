"""CVE-2022-23491 — certifi compromised root CA (TrustCor).

The certifi package included the TrustCor root CA certificates, which were
found to be operated by a company with ties to a US intelligence contractor.
Applications trusting certifi's CA bundle implicitly trusted TrustCor-issued
certificates.

Affected: certifi < 2022.12.07
"""

CODE = '''\
import requests

def fetch_secure(url):
    """Fetch a URL with TLS verification via certifi CA bundle."""
    resp = requests.get(url, verify=True)  # uses certifi bundle
    resp.raise_for_status()
    return resp.json()

# The certifi CA bundle (< 2022.12.07) includes TrustCor root CA
# certificates. TrustCor was found to have ties to a US intelligence
# contractor, and could issue valid TLS certificates for any domain.
# Any HTTPS request verified against this bundle trusts TrustCor-signed certs.
'''

CVE = {
    "cve_id": "CVE-2022-23491",
    "severity": "medium",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "The certifi CA bundle includes TrustCor root certificates. An entity "
        "with access to TrustCor's signing infrastructure could issue valid TLS "
        "certificates for any domain, enabling MITM attacks that pass standard "
        "certificate verification."
    ),
    "fix": (
        "Upgrade certifi to >= 2022.12.07, which removes the TrustCor root CAs. "
        "Alternatively, pin to a custom CA bundle that excludes untrusted roots."
    ),
}
