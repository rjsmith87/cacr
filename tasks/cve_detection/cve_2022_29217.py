"""CVE-2022-29217 — PyJWT algorithm confusion attack.

PyJWT allows an attacker to forge tokens by exploiting algorithm confusion when
the server accepts multiple algorithms but uses a public key. The attacker signs
with HMAC using the public key as the secret.

Affected: PyJWT < 2.4.0
"""

CODE = '''\
import jwt

# RS256 public key used for verification (loaded from config)
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3xfn/yGKV
... (truncated for brevity) ...
wQIDAQAB
-----END PUBLIC KEY-----"""

def verify_token(token):
    """Verify a JWT token from the client."""
    try:
        payload = jwt.decode(
            token,
            PUBLIC_KEY,
            algorithms=["RS256", "HS256"],
        )
        return payload
    except jwt.InvalidTokenError:
        return None

# An attacker crafts a token signed with HS256 using the PUBLIC_KEY as
# the HMAC secret. Since HS256 is in the allowed algorithms list, PyJWT
# accepts the forged token.
'''

CVE = {
    "cve_id": "CVE-2022-29217",
    "severity": "critical",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "The algorithms list includes both RS256 and HS256. An attacker obtains "
        "the public key (which is public), signs a forged JWT using HS256 with "
        "the public key as the HMAC secret. PyJWT accepts this because HS256 is "
        "in the allowed list and the 'key' parameter matches."
    ),
    "fix": (
        "Remove HS256 from the algorithms list — only allow RS256 when verifying "
        "with a public key. Upgrade PyJWT to >= 2.4.0 which adds safeguards "
        "against algorithm confusion. Use algorithms=['RS256'] exclusively."
    ),
}
