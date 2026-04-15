"""Smoke test — head-to-head Flash vs Flash Lite on the 12-CVE battery.

Throwaway diagnostic. Does NOT touch pipelines/. Confirms whether the prior
12/12 vs 6/12 accuracy gap still exists on current model versions before we
commit to Phase 2 (CVE study + RouteLLM comparison).

Usage: python scripts/smoke_test_cve.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv()
except ImportError:
    pass

from models.gemini_adapter import GeminiFlash  # noqa: E402
from models.gemini_flash_lite_adapter import GeminiFlashLite  # noqa: E402
from tasks.cve_detection import ALL_CVES  # noqa: E402

# Gold vuln_class per CVE — mapped from the attack_vector text to the
# fixed taxonomy defined in the pre-registration. Done here (not in the
# task records) because this is a throwaway script.
VULN_CLASS_GOLD = {
    "CVE-2023-30861": "Information Disclosure",   # Flask session cookie cache disclosure
    "CVE-2023-32681": "Information Disclosure",   # Requests Proxy-Authorization leak on redirect
    "CVE-2018-18074": "Information Disclosure",   # Requests auth leak on redirect
    "CVE-2019-11324": "Cryptographic Failure",    # urllib3 cert verify bypass
    "CVE-2022-29217": "Authentication Bypass",    # PyJWT algorithm confusion
    "CVE-2021-33503": "ReDoS",                    # urllib3 ReDoS
    "CVE-2020-28493": "ReDoS",                    # Jinja2 ReDoS
    "CVE-2021-28363": "Cryptographic Failure",    # urllib3 HTTPS proxy MITM
    "CVE-2022-23491": "Cryptographic Failure",    # certifi compromised root CA
    "CVE-2023-25577": "Other",                    # Werkzeug multipart DoS (resource exhaustion)
    "CVE-2020-26137": "Injection",                # urllib3 CRLF injection
    "CVE-2019-20477": "Deserialization",          # PyYAML FullLoader RCE
}

TAXONOMY = [
    "Injection", "Deserialization", "Prototype Pollution", "Authentication Bypass",
    "Information Disclosure", "SSRF", "Path Traversal", "Cryptographic Failure",
    "ReDoS", "Other",
]

PROMPT_TEMPLATE = """You are reviewing a code snippet for security vulnerabilities.
Identify the most serious vulnerability present.

Respond in strict JSON (no markdown, no prose outside the JSON):
{{"vuln_class": "<one of: {taxonomy}>",
 "severity": "<critical|high|medium|low>",
 "confidence": <integer 0-10>,
 "reasoning": "<<=40 words>"}}

Code (python):
```python
{code}
```"""


def _parse_response(text: str) -> dict | None:
    """Extract the JSON object from a model response. Tolerant to fences."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _score(parsed: dict | None, cve: dict) -> dict:
    if not parsed:
        return {
            "vuln_class_pred": None, "severity_pred": None, "confidence": None,
            "vuln_class_correct": False, "severity_correct": False,
            "both_correct": False, "parse_error": True,
        }
    vc_pred = str(parsed.get("vuln_class", "")).strip()
    sev_pred = str(parsed.get("severity", "")).strip().lower()
    try:
        conf = int(parsed.get("confidence"))
    except (TypeError, ValueError):
        conf = None
    vc_gold = VULN_CLASS_GOLD[cve["cve_id"]]
    sev_gold = cve["severity"].lower()
    vc_ok = vc_pred == vc_gold
    sev_ok = sev_pred == sev_gold
    return {
        "vuln_class_pred": vc_pred, "severity_pred": sev_pred, "confidence": conf,
        "vuln_class_correct": vc_ok, "severity_correct": sev_ok,
        "both_correct": vc_ok and sev_ok, "parse_error": False,
    }


def _call(model, prompt: str) -> tuple[str, float]:
    t0 = time.time()
    try:
        out = model.generate(prompt)
    except Exception as exc:  # noqa: BLE001
        return f"__ERROR__: {exc}", (time.time() - t0) * 1000
    return out, (time.time() - t0) * 1000


def main() -> int:
    taxonomy_str = ", ".join(TAXONOMY)

    models = {
        "flash-lite": GeminiFlashLite(),
        "flash": GeminiFlash(),
    }

    rows: list[dict] = []
    for cve in ALL_CVES:
        prompt = PROMPT_TEMPLATE.format(taxonomy=taxonomy_str, code=cve["code"])
        per_cve = {"cve_id": cve["cve_id"], "severity_gold": cve["severity"],
                   "vuln_class_gold": VULN_CLASS_GOLD[cve["cve_id"]], "models": {}}
        for mname, model in models.items():
            raw, latency_ms = _call(model, prompt)
            parsed = _parse_response(raw) if not raw.startswith("__ERROR__") else None
            scored = _score(parsed, cve)
            per_cve["models"][mname] = {
                "raw": raw, "parsed": parsed, "latency_ms": round(latency_ms, 1),
                **scored,
            }
            print(f"  {cve['cve_id']} [{mname:10}] "
                  f"vc={scored['vuln_class_correct']!s:5} "
                  f"sev={scored['severity_correct']!s:5} "
                  f"conf={scored['confidence']}", file=sys.stderr)
        rows.append(per_cve)

    # ── Comparison table ───────────────────────────────────────────────
    print()
    print(f"{'CVE ID':<16} | {'FL vc':<5} | {'FL sev':<6} | {'F vc':<5} | "
          f"{'F sev':<5} | {'FL conf':<7} | {'F conf':<6}")
    print("-" * 72)
    fl_both = f_both = fl_vc = f_vc = fl_sev = f_sev = 0
    for r in rows:
        fl = r["models"]["flash-lite"]; f = r["models"]["flash"]
        fl_vc += int(fl["vuln_class_correct"]); f_vc += int(f["vuln_class_correct"])
        fl_sev += int(fl["severity_correct"]); f_sev += int(f["severity_correct"])
        fl_both += int(fl["both_correct"]); f_both += int(f["both_correct"])
        print(f"{r['cve_id']:<16} | "
              f"{'Y' if fl['vuln_class_correct'] else 'N':<5} | "
              f"{'Y' if fl['severity_correct'] else 'N':<6} | "
              f"{'Y' if f['vuln_class_correct'] else 'N':<5} | "
              f"{'Y' if f['severity_correct'] else 'N':<5} | "
              f"{str(fl['confidence']):<7} | {str(f['confidence']):<6}")
    n = len(rows)
    print("-" * 72)
    print(f"Flash Lite: vuln_class {fl_vc}/{n}  severity {fl_sev}/{n}  both {fl_both}/{n}")
    print(f"Flash     : vuln_class {f_vc}/{n}   severity {f_sev}/{n}   both {f_both}/{n}")

    out_path = Path(__file__).resolve().parents[1] / "docs" / "smoke_test_raw.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model_versions": {m: models[m].name for m in models},
        "n": n,
        "totals": {
            "flash-lite": {"vuln_class": fl_vc, "severity": fl_sev, "both": fl_both},
            "flash":      {"vuln_class": f_vc,  "severity": f_sev,  "both": f_both},
        },
        "rows": rows,
    }, indent=2))
    print(f"\nRaw results saved to {out_path.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
