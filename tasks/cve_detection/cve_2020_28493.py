"""CVE-2020-28493 — Jinja2 ReDoS via template rendering.

Jinja2's urlize filter uses a regex pattern that exhibits catastrophic
backtracking on certain crafted input strings.

Affected: Jinja2 < 2.11.3
"""

CODE = '''\
from jinja2 import Environment

env = Environment()

def render_comment(comment_text):
    """Render user comment with auto-linked URLs."""
    template = env.from_string("{{ text | urlize }}")
    return template.render(text=comment_text)

# An attacker submits a comment with a crafted string like:
# render_comment("http://" + "a" * 100000)
# The urlize filter regex backtracks catastrophically, hanging the process.
'''

CVE = {
    "cve_id": "CVE-2020-28493",
    "severity": "medium",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "User-provided text is passed to Jinja2's urlize filter, which uses "
        "a regex vulnerable to catastrophic backtracking on long strings "
        "resembling partial URLs. An attacker submits a crafted comment that "
        "causes the rendering thread to hang indefinitely."
    ),
    "fix": (
        "Upgrade Jinja2 to >= 2.11.3 which fixes the urlize regex. Additionally, "
        "truncate or sanitize user input length before passing to template rendering."
    ),
}
