"""CVE-2020-26137 — urllib3 CRLF injection in HTTP headers.

urllib3 does not properly validate header values, allowing CRLF characters
that can inject additional HTTP headers or split responses.

Affected: urllib3 < 1.25.9
"""

CODE = '''\
import urllib3

http = urllib3.PoolManager()

def set_custom_header(url, header_name, header_value):
    """Make a request with a user-specified custom header."""
    resp = http.request(
        "GET",
        url,
        headers={
            header_name: header_value,
            "Accept": "application/json",
        },
    )
    return resp.data

# An attacker controls header_value and injects:
# header_value = "legit\\r\\nX-Injected: malicious\\r\\n\\r\\nSMUGGLED BODY"
# This injects additional headers and potentially a smuggled request body.
'''

CVE = {
    "cve_id": "CVE-2020-26137",
    "severity": "medium",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "User-controlled input is passed as an HTTP header value without CRLF "
        "sanitization. An attacker injects \\r\\n sequences to add arbitrary "
        "headers or split the HTTP response, enabling header injection or "
        "request smuggling."
    ),
    "fix": (
        "Upgrade urllib3 to >= 1.25.9, which rejects header values containing "
        "CR or LF characters. Also validate and sanitize all user input before "
        "using it in HTTP headers."
    ),
}
