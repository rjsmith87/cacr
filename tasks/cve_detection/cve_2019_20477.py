"""CVE-2019-20477 — PyYAML arbitrary code execution via FullLoader.

PyYAML's FullLoader (which was supposed to be safe) allows arbitrary
Python object instantiation through the !!python/object/new constructor,
enabling remote code execution.

Affected: PyYAML < 5.4
"""

CODE = '''\
import yaml
from flask import Flask, request

app = Flask(__name__)

@app.route("/config", methods=["POST"])
def update_config():
    """Accept YAML configuration from admin users."""
    config = yaml.load(request.data, Loader=yaml.FullLoader)
    apply_settings(config)
    return "OK"

# FullLoader was introduced as a "safe" alternative to yaml.Loader,
# but it still allows !!python/object/new and !!python/object/apply
# constructors, enabling arbitrary object instantiation.
# Payload: !!python/object/new:os.system ["rm -rf /"]
'''

CVE = {
    "cve_id": "CVE-2019-20477",
    "severity": "critical",
    "code": CODE,
    "is_vulnerable": True,
    "attack_vector": (
        "User-provided YAML is parsed with FullLoader, which allows "
        "!!python/object/new and !!python/object/apply constructors. An attacker "
        "submits a YAML payload that instantiates os.system or subprocess.Popen, "
        "achieving remote code execution on the server."
    ),
    "fix": (
        "Use yaml.safe_load() or yaml.load(data, Loader=yaml.SafeLoader) instead "
        "of FullLoader. Upgrade PyYAML to >= 5.4 which restricts FullLoader. "
        "Never parse untrusted YAML with anything other than SafeLoader."
    ),
}
