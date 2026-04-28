"""Cascade Demo runner: build the canonical JSON for the dashboard.

Runs a 3-step pipeline (severity → vulnerability detection → fix proposal)
on a single CVE, twice — once with All-Flash (every step uses
gemini-2.5-flash) and once with CACR-Routed (each step picks the
cheapest passing model from the cost matrix per task family).

Persists the full per-step record (model, prompt summary, raw output,
parsed fields, confidence, latency, cost) to
dashboard/src/data/cascade_demo.json so the dashboard tab can render
the side-by-side without making live API calls on every page load.

The contrast we surface is intentionally NOT capability (both pipelines
detect the bug — Flash genuinely solves CVE detection now). The
contrast is cost, latency, and confidence calibration. If the data
shows otherwise, the runner just records what it sees and the
dashboard's `what_happened` text is written after-the-fact to match.

Usage:
    set -a && . ./.env && set +a
    python pipelines/cascade_demo.py [--cve CVE-ID]

Default CVE: CVE-2023-30861 (Flask session cookie disclosure).
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from runner import _load_dotenv  # noqa: E402

_load_dotenv(os.path.join(_ROOT, ".env"))

from models.anthropic_adapter import ClaudeHaiku  # noqa: E402
from models.claude_opus_adapter import ClaudeOpus  # noqa: E402
from models.gemini_adapter import GeminiFlash  # noqa: E402
from models.gemini_flash_lite_adapter import GeminiFlashLite  # noqa: E402
from models.gemini_pro_adapter import GeminiPro  # noqa: E402
from models.gpt5_adapter import GPT5  # noqa: E402
from models.o3_adapter import O3  # noqa: E402
from models.openai_adapter import GPT4oMini  # noqa: E402
from router.cost_model import MODEL_COSTS  # noqa: E402
from router.policy import LookupTableRouter, RoutingDecision  # noqa: E402
from tasks.cve_detection import ALL_CVES  # noqa: E402


# ── Prompts ──────────────────────────────────────────────────────────
SEVERITY_PROMPT = """\
You are reviewing a Python code snippet for security risk. Rate the severity
of any vulnerability you can identify.

```python
{code}
```

Respond in EXACTLY this format (2 lines, nothing else):
severity: critical, high, medium, low, or none
confidence: 1-10"""

DETECTION_PROMPT = """\
You are reviewing a Python code snippet for security vulnerabilities. A
prior step rated its severity as: {severity}.

```python
{code}
```

Respond in EXACTLY this format (3 lines, nothing else):
vulnerable: yes or no
vulnerability_type: a short snake_case identifier (e.g. sql_injection, session_fixation, credential_disclosure, path_traversal)
confidence: 1-10"""

FIX_PROMPT = """\
You are proposing a fix for a security vulnerability in this Python code.
Prior steps identified the vulnerability as: {vulnerability_type}
(severity: {severity}).

```python
{code}
```

Respond in EXACTLY this format (2 lines, nothing else):
fix: a one-paragraph remediation describing the code change required
confidence: 1-10"""


# ── Parsers ──────────────────────────────────────────────────────────
def _parse_step1(out: str) -> dict:
    severity = None
    confidence = None
    for line in (out or "").lower().splitlines():
        line = line.strip()
        if line.startswith("severity:"):
            for s in ("critical", "high", "medium", "low", "none"):
                if s in line:
                    severity = s
                    break
        elif line.startswith("confidence:"):
            m = re.search(r"\d+", line)
            if m:
                confidence = int(m.group(0))
    return {"severity": severity, "confidence": confidence}


def _parse_step2(out: str) -> dict:
    is_vulnerable = None
    vuln_type = None
    confidence = None
    for line in (out or "").splitlines():
        lower = line.lower().strip()
        if lower.startswith("vulnerable:"):
            is_vulnerable = "yes" in lower
        elif lower.startswith("vulnerability_type:"):
            vuln_type = line.split(":", 1)[1].strip().split()[0] if ":" in line else None
        elif lower.startswith("confidence:"):
            m = re.search(r"\d+", lower)
            if m:
                confidence = int(m.group(0))
    return {"is_vulnerable": is_vulnerable, "vulnerability_type": vuln_type, "confidence": confidence}


def _parse_step3(out: str) -> dict:
    fix_text = None
    confidence = None
    for line in (out or "").splitlines():
        lower = line.lower().strip()
        if lower.startswith("fix:"):
            fix_text = line.split(":", 1)[1].strip()
        elif lower.startswith("confidence:"):
            m = re.search(r"\d+", lower)
            if m:
                confidence = int(m.group(0))
    return {"fix": fix_text, "confidence": confidence}


# ── Cost helper ──────────────────────────────────────────────────────
def _estimate_cost(model_name: str, prompt: str, output: str) -> float:
    """Char/4 token estimate × per-token rates from MODEL_COSTS."""
    rates = MODEL_COSTS.get(model_name)
    if not rates:
        return 0.0
    in_tok = max(1, len(prompt) // 4)
    out_tok = max(1, len(output) // 4)
    return in_tok * rates["input"] + out_tok * rates["output"]


# ── Model lookup for CACR routing ────────────────────────────────────
_ADAPTER_BY_NAME = {
    "claude-haiku-4-5": ClaudeHaiku,
    "claude-opus-4-7": ClaudeOpus,
    "gemini-2.5-flash": GeminiFlash,
    "gemini-2.5-flash-lite": GeminiFlashLite,
    "gemini-2.5-pro": GeminiPro,
    "gpt-4o-mini": GPT4oMini,
    "gpt-5": GPT5,
    "o3": O3,
}


def _get_adapter(name: str):
    cls = _ADAPTER_BY_NAME.get(name)
    if not cls:
        raise ValueError(f"No adapter for model {name!r}")
    return cls()


def _route_for_task(task: str) -> RoutingDecision:
    """Return the full RoutingDecision (model + below_threshold + warning)."""
    router = LookupTableRouter()
    return router.route(task)


# ── Step runner ──────────────────────────────────────────────────────
def _run_step(model, model_name: str, prompt: str, parser, prompt_summary: str, step_num: int, step_name: str) -> dict:
    t0 = time.perf_counter()
    output = ""
    error = None
    try:
        output = model.generate(prompt)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - t0) * 1000

    parsed = parser(output)
    cost = _estimate_cost(model_name, prompt, output)

    return {
        "step": step_num,
        "name": step_name,
        "model": model_name,
        "prompt_summary": prompt_summary,
        "prompt_length_chars": len(prompt),
        "output": output,
        "output_truncated": output if len(output) <= 400 else output[:400] + "…",
        "parsed": parsed,
        "confidence": parsed.get("confidence"),
        "latency_ms": round(latency_ms, 1),
        "cost_usd": round(cost, 8),
        "error": error,
    }


def run_pipeline(
    cve: dict,
    strategy_name: str,
    model_per_step: list[str],
    routing_per_step: list[dict] | None = None,
) -> dict:
    """Run the 3-step pipeline using the supplied model-per-step list.

    model_per_step: [step1_model, step2_model, step3_model] — names,
    not adapter instances (we instantiate fresh each call so the
    side-effects of one step don't leak into another).

    routing_per_step: optional list of routing-context dicts per step
    (e.g. {"task": "SecurityVuln", "below_threshold": False, "warning": None})
    so the dashboard can show which task family the router treated
    each step as and whether the all-fail warning fired.
    """
    print(f"\n=== {strategy_name} ===")
    steps: list[dict] = []

    # Step 1 — severity
    m1 = _get_adapter(model_per_step[0])
    s1 = _run_step(
        m1, model_per_step[0],
        SEVERITY_PROMPT.format(code=cve["code"]),
        _parse_step1,
        "Rate severity of any vulnerability in this code (critical/high/medium/low/none)",
        1, "Severity classification",
    )
    print(f"  step 1 {s1['model']:22s} sev={s1['parsed'].get('severity')} conf={s1['confidence']} lat={s1['latency_ms']:.0f}ms cost=${s1['cost_usd']:.6f}")
    steps.append(s1)

    # Step 2 — vulnerability detection (uses severity from step 1)
    sev_for_step2 = s1["parsed"].get("severity") or "unknown"
    m2 = _get_adapter(model_per_step[1])
    s2 = _run_step(
        m2, model_per_step[1],
        DETECTION_PROMPT.format(code=cve["code"], severity=sev_for_step2),
        _parse_step2,
        f"Identify vulnerability type given severity={sev_for_step2}",
        2, "Vulnerability detection",
    )
    print(f"  step 2 {s2['model']:22s} vuln={s2['parsed'].get('is_vulnerable')} type={s2['parsed'].get('vulnerability_type')} conf={s2['confidence']} lat={s2['latency_ms']:.0f}ms cost=${s2['cost_usd']:.6f}")
    steps.append(s2)

    # Step 3 — fix proposal (uses both severity and vuln type)
    vt_for_step3 = s2["parsed"].get("vulnerability_type") or "unknown"
    m3 = _get_adapter(model_per_step[2])
    s3 = _run_step(
        m3, model_per_step[2],
        FIX_PROMPT.format(code=cve["code"], severity=sev_for_step2, vulnerability_type=vt_for_step3),
        _parse_step3,
        f"Propose remediation for {vt_for_step3} ({sev_for_step2} severity)",
        3, "Fix proposal",
    )
    print(f"  step 3 {s3['model']:22s} conf={s3['confidence']} lat={s3['latency_ms']:.0f}ms cost=${s3['cost_usd']:.6f}")
    steps.append(s3)

    # Attach routing context per step (if supplied) so the dashboard
    # can render the task-family + below_threshold + warning state.
    if routing_per_step:
        for step, routing in zip(steps, routing_per_step):
            step["routing"] = routing

    total_cost = sum(s["cost_usd"] for s in steps)
    total_latency = sum(s["latency_ms"] for s in steps)

    # Outcome assessment — both pipelines should detect on this CVE
    detected = bool(s2["parsed"].get("is_vulnerable"))
    fix_proposed = bool(s3["parsed"].get("fix"))
    confidences = [s["confidence"] for s in steps if s["confidence"] is not None]
    conf_min = min(confidences) if confidences else None
    conf_max = max(confidences) if confidences else None
    conf_variance = (conf_max - conf_min) if confidences else None

    return {
        "strategy": strategy_name,
        "models_used": list(dict.fromkeys(model_per_step)),  # dedup, preserve order
        "steps": steps,
        "total_cost_usd": round(total_cost, 8),
        "total_latency_ms": round(total_latency, 1),
        "outcome": {
            "vulnerability_detected": detected,
            "fix_proposed": fix_proposed,
        },
        "confidence_stats": {
            "min": conf_min,
            "max": conf_max,
            "spread": conf_variance,
            "values": confidences,
        },
    }


# ── Main ─────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cve", default="CVE-2023-30861")
    args = parser.parse_args(argv[1:])

    cve = next((c for c in ALL_CVES if c["cve_id"] == args.cve), None)
    if not cve:
        print(f"ERROR: CVE {args.cve!r} not in battery.", file=sys.stderr)
        print(f"Available: {[c['cve_id'] for c in ALL_CVES]}", file=sys.stderr)
        return 1

    print(f"=== Cascade Demo on {cve['cve_id']} (gold severity: {cve['severity']}) ===")
    print(f"Code length: {len(cve['code'])} chars")

    # Strategy A: All Flash — every step uses gemini-2.5-flash
    all_flash_models = ["gemini-2.5-flash"] * 3
    all_flash_routing = [
        {"task": None, "rationale": "fixed strategy: every step uses gemini-2.5-flash",
         "below_threshold": False, "warning": None}
    ] * 3

    # Strategy B: CACR Routed — router picks per task family.
    # Steps 1 & 2 are SecurityVuln-shaped; step 3 (fix generation) is
    # CodeSummarization-shaped, where no model in the matrix meets the
    # 0.70 minimum acceptable score, so the router returns the highest-
    # scoring fallback (Opus 4.7 at 0.52) WITH a below_threshold flag
    # and a warning string. This is the cascade mechanism doing its
    # job: escalating when SLMs aren't good enough, and saying so.
    sec = _route_for_task("SecurityVuln")
    summ = _route_for_task("CodeSummarization")
    cacr_models = [sec.recommended_model, sec.recommended_model, summ.recommended_model]
    cacr_routing = [
        {"task": "SecurityVuln", "rationale": sec.reasoning,
         "below_threshold": sec.below_threshold, "warning": sec.warning},
        {"task": "SecurityVuln", "rationale": sec.reasoning,
         "below_threshold": sec.below_threshold, "warning": sec.warning},
        {"task": "CodeSummarization", "rationale": summ.reasoning,
         "below_threshold": summ.below_threshold, "warning": summ.warning},
    ]
    print(f"\nRouter picks:")
    print(f"  SecurityVuln (steps 1+2)  → {sec.recommended_model}  below_threshold={sec.below_threshold}")
    print(f"  CodeSummarization (step 3) → {summ.recommended_model}  below_threshold={summ.below_threshold}")
    if summ.warning:
        print(f"    warning: {summ.warning}")

    started = datetime.now(timezone.utc).isoformat()
    all_flash = run_pipeline(cve, "All Flash", all_flash_models, all_flash_routing)
    cacr = run_pipeline(cve, "CACR Routed", cacr_models, cacr_routing)
    finished = datetime.now(timezone.utc).isoformat()

    bundle = {
        "generated_at_utc": started,
        "finished_at_utc": finished,
        "cve": {
            "id": cve["cve_id"],
            "severity_gold": cve["severity"],
            "is_vulnerable_gold": cve["is_vulnerable"],
            "code": cve["code"],
            "attack_vector": cve.get("attack_vector"),
            "expected_fix": cve.get("fix"),
        },
        "all_flash": all_flash,
        "cacr_routed": cacr,
        "comparison": {
            "cost_ratio_flash_over_cacr": (
                round(all_flash["total_cost_usd"] / cacr["total_cost_usd"], 2)
                if cacr["total_cost_usd"] > 0 else None
            ),
            "latency_ratio_flash_over_cacr": (
                round(all_flash["total_latency_ms"] / cacr["total_latency_ms"], 2)
                if cacr["total_latency_ms"] > 0 else None
            ),
            "both_detected": all_flash["outcome"]["vulnerability_detected"]
                              and cacr["outcome"]["vulnerability_detected"],
            "all_flash_confidence_spread": all_flash["confidence_stats"]["spread"],
            "cacr_confidence_spread": cacr["confidence_stats"]["spread"],
        },
    }

    out_path = os.path.join(_ROOT, "dashboard", "src", "data", "cascade_demo.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(bundle, f, indent=2)
    print(f"\nWrote {out_path}")
    print(f"\nFlash:  cost=${all_flash['total_cost_usd']:.6f}  latency={all_flash['total_latency_ms']:.0f}ms  conf={all_flash['confidence_stats']['values']}")
    print(f"CACR:   cost=${cacr['total_cost_usd']:.6f}  latency={cacr['total_latency_ms']:.0f}ms  conf={cacr['confidence_stats']['values']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
