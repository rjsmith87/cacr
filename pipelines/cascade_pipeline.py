"""Generic 3-step cascade pipeline runner.

Layer 1's exec layer: takes a code snippet, a task family, and two
strategies, and runs the same severity → detection → fix pipeline
under each strategy. For "cacr", uses the CascadeAwareRouter so each
step gets cheapest-passing routing with runtime escalation if
confidence is low. For "All [model]", every step uses that one model
with no escalation.

Each step's prompt includes the prior step's accepted_output as
context — that's the cascade. Step 2 sees step 1's severity,
step 3 sees step 1's severity AND step 2's issue type.

Cascade-failure detection is intentionally simple: contradictions
between adjacent steps (e.g. step 1 says severity=none but step 2
says vulnerable=yes) and propagated model errors.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Callable

from router.cascade_router import (
    CascadeAwareRouter,
    CascadeResult,
    _default_model_runner,
)


# ── Prompt templates ─────────────────────────────────────────────────
SEVERITY_PROMPT = """\
Review this Python code for security or correctness issues. Rate the
severity of any vulnerability or bug present.

```python
{code}
```

Respond in EXACTLY this format (2 lines, nothing else):
severity: critical, high, medium, low, or none
confidence: 1-10"""


DETECTION_PROMPT = """\
Analyze this Python code. A prior step rated severity as: {severity}.

```python
{code}
```

Identify the type of vulnerability or bug and confirm whether it is real.

Respond in EXACTLY this format (3 lines, nothing else):
vulnerable: yes or no
issue_type: a short snake_case identifier (e.g. sql_injection,
            session_fixation, off_by_one, race_condition)
confidence: 1-10"""


FIX_PROMPT = """\
Propose a fix for the issue in this Python code.
Severity: {severity}
Issue type: {issue_type}

```python
{code}
```

Respond in EXACTLY this format (2 lines, nothing else):
fix: a one-paragraph remediation describing the code change required
confidence: 1-10"""


# ── Parsers ──────────────────────────────────────────────────────────
_CONF_RE = re.compile(r"confidence:\s*(\d+)", re.IGNORECASE)
_SEV_RE = re.compile(r"severity:\s*(critical|high|medium|low|none)", re.IGNORECASE)
_VULN_RE = re.compile(r"vulnerable:\s*(yes|no)", re.IGNORECASE)
_ISSUE_RE = re.compile(r"issue_type:\s*(\S+)", re.IGNORECASE)
_FIX_RE = re.compile(r"fix:\s*(.+)", re.IGNORECASE | re.DOTALL)


def parse_confidence(out: str | None) -> int | None:
    if not out:
        return None
    m = _CONF_RE.search(out)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 10 else None


def _parse_severity(out: str | None) -> str | None:
    if not out:
        return None
    m = _SEV_RE.search(out)
    return m.group(1).lower() if m else None


def _parse_vulnerable(out: str | None) -> bool | None:
    if not out:
        return None
    m = _VULN_RE.search(out)
    if not m:
        return None
    return m.group(1).lower() == "yes"


def _parse_issue_type(out: str | None) -> str | None:
    if not out:
        return None
    m = _ISSUE_RE.search(out)
    return m.group(1).lower() if m else None


def _parse_fix(out: str | None) -> str | None:
    if not out:
        return None
    m = _FIX_RE.search(out)
    return m.group(1).strip() if m else None


# ── Single-model (non-cascade) step runner ───────────────────────────
def _direct_step(
    model_runner: Callable[[str, str], dict],
    model_name: str,
    prompt: str,
) -> dict[str, Any]:
    """Run one step with a fixed model. Same dict shape as the
    CascadeResult-as-dict produced by _cascade_step, with escalation
    fields set to None and below_threshold=False — keeps the JSON
    response shape identical regardless of strategy."""
    r = model_runner(model_name, prompt)
    output = r.get("output", "") or ""
    confidence = parse_confidence(output)
    return {
        "initial_model": model_name,
        "initial_output": output,
        "initial_confidence": confidence,
        "initial_cost": float(r.get("cost_usd", 0.0)),
        "initial_latency": float(r.get("latency_ms", 0.0)),
        "escalated": False,
        "escalation_model": None,
        "escalation_output": None,
        "escalation_confidence": None,
        "escalation_cost": None,
        "escalation_latency": None,
        "accepted_output": output,
        "accepted_model": model_name,
        "accepted_confidence": confidence,
        "below_threshold": False,
        "warning": None,
        "initial_error": r.get("error"),
        "escalation_error": None,
    }


def _cascade_step(
    router: CascadeAwareRouter, prompt: str, task: str
) -> dict[str, Any]:
    result: CascadeResult = router.run_step(prompt, task, parse_confidence)
    return asdict(result)


# ── Strategy runner ──────────────────────────────────────────────────
def _step_total_cost(step: dict) -> float:
    return float(step.get("initial_cost") or 0.0) + float(
        step.get("escalation_cost") or 0.0
    )


def _step_total_latency(step: dict) -> float:
    return float(step.get("initial_latency") or 0.0) + float(
        step.get("escalation_latency") or 0.0
    )


def _run_strategy(
    strategy: str,
    code: str,
    task: str,
    threshold: float,
    model_runner: Callable[[str, str], dict] | None,
) -> dict[str, Any]:
    """Run the 3-step pipeline under one strategy and return a dict
    with steps, totals, and a cascade-failure list."""
    runner = model_runner if model_runner is not None else _default_model_runner

    is_cacr = strategy == "cacr"
    cascade_router: CascadeAwareRouter | None = None
    if is_cacr:
        cascade_router = CascadeAwareRouter(
            model_runner=runner,
            escalation_threshold=threshold,
        )

    def step(prompt: str) -> dict[str, Any]:
        if is_cacr:
            assert cascade_router is not None
            return _cascade_step(cascade_router, prompt, task)
        return _direct_step(runner, strategy, prompt)

    # Step 1: severity classification.
    s1 = step(SEVERITY_PROMPT.format(code=code))
    severity = _parse_severity(s1["accepted_output"]) or "unknown"

    # Step 2: vulnerability detection — uses step 1's severity.
    s2 = step(DETECTION_PROMPT.format(code=code, severity=severity))
    issue_type = _parse_issue_type(s2["accepted_output"]) or "unknown"

    # Step 3: fix proposal — uses both prior outputs.
    s3 = step(
        FIX_PROMPT.format(
            code=code, severity=severity, issue_type=issue_type
        )
    )

    steps = [s1, s2, s3]
    total_cost = sum(_step_total_cost(s) for s in steps)
    total_latency = sum(_step_total_latency(s) for s in steps)

    return {
        "strategy": strategy,
        "task": task,
        "steps": steps,
        "step_summary": {
            "severity": severity,
            "vulnerable": _parse_vulnerable(s2["accepted_output"]),
            "issue_type": issue_type,
            "fix_present": bool(_parse_fix(s3["accepted_output"])),
        },
        "total_cost_usd": round(total_cost, 8),
        "total_latency_ms": round(total_latency, 1),
        "any_escalated": any(s.get("escalated") for s in steps),
        "any_below_threshold": any(s.get("below_threshold") for s in steps),
        "cascade_failures": _detect_cascade_failures(steps),
    }


# ── Cascade-failure heuristic ────────────────────────────────────────
def _detect_cascade_failures(steps: list[dict]) -> list[dict]:
    """Simple inconsistency checks between adjacent steps + error
    propagation. Not exhaustive — the user explicitly asked us not
    to overthink this."""
    failures: list[dict] = []
    if len(steps) != 3:
        return failures
    s1, s2, s3 = steps

    sev = _parse_severity(s1.get("accepted_output", ""))
    vuln = _parse_vulnerable(s2.get("accepted_output", ""))
    fix = _parse_fix(s3.get("accepted_output", ""))

    # Step 1 said no severity but step 2 says vulnerable.
    if sev == "none" and vuln is True:
        failures.append({
            "between_steps": "1->2",
            "reason": "step 1 reported severity=none but step 2 said vulnerable=yes",
        })

    # Step 2 said not vulnerable but step 3 still produced a fix.
    if vuln is False and fix and len(fix) > 20:
        failures.append({
            "between_steps": "2->3",
            "reason": "step 2 reported vulnerable=no but step 3 produced a non-trivial fix",
        })

    # Any model-runner error propagated through.
    for i, s in enumerate(steps, start=1):
        if s.get("initial_error"):
            failures.append({
                "step": i,
                "reason": f"step {i} initial run errored: {s['initial_error']}",
            })
        if s.get("escalation_error"):
            failures.append({
                "step": i,
                "reason": f"step {i} escalation run errored: {s['escalation_error']}",
            })

    return failures


# ── Public entrypoint ────────────────────────────────────────────────
def run_pipeline(
    code_snippet: str,
    task: str,
    strategy_a: str,
    strategy_b: str,
    escalation_threshold: float = 7.0,
    model_runner: Callable[[str, str], dict] | None = None,
) -> dict[str, Any]:
    """Run both strategies through the same 3-step pipeline and return
    a side-by-side comparison.

    Inputs are validated by the API layer before this is called; this
    function trusts them. `model_runner` is injectable for tests.
    """
    a = _run_strategy(strategy_a, code_snippet, task, escalation_threshold, model_runner)
    b = _run_strategy(strategy_b, code_snippet, task, escalation_threshold, model_runner)

    cost_ratio = (
        round(a["total_cost_usd"] / b["total_cost_usd"], 2)
        if b["total_cost_usd"] > 0 else None
    )
    latency_ratio = (
        round(a["total_latency_ms"] / b["total_latency_ms"], 2)
        if b["total_latency_ms"] > 0 else None
    )

    return {
        "task": task,
        "escalation_threshold": escalation_threshold,
        "code_snippet_length_chars": len(code_snippet),
        "strategy_a": a,
        "strategy_b": b,
        "comparison": {
            "cost_ratio_a_over_b": cost_ratio,
            "latency_ratio_a_over_b": latency_ratio,
            "a_has_cascade_failures": len(a["cascade_failures"]) > 0,
            "b_has_cascade_failures": len(b["cascade_failures"]) > 0,
            "a_below_threshold": a["any_below_threshold"],
            "b_below_threshold": b["any_below_threshold"],
            "a_escalated": a["any_escalated"],
            "b_escalated": b["any_escalated"],
        },
    }
