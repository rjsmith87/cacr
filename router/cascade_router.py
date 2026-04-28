"""Cascade-aware router with runtime confidence-based escalation.

Layer 1 of cascade-aware routing: wraps the static LookupTableRouter
with a per-step escalation rule that fires when the cheapest passing
model returns a confidence below a configurable threshold. Maximum
one escalation per step — the router will not loop chasing
confidence forever; if even the escalated model is uncertain, it
flags `below_threshold` and proceeds.

The CascadeAwareRouter is intentionally pure logic: it does not
construct adapters itself, it does not parse model output, and it
does not know what a "step" means at the pipeline level. It accepts
a model_runner callable and a parse_confidence callable as
dependencies, which makes it trivial to unit-test with mocked
models. The default model_runner instantiates fresh adapters from
the existing models/ package on each call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from router.cost_model import MODEL_COSTS
from router.policy import LookupTableRouter, MIN_ACCEPTABLE_SCORE


@dataclass
class CascadeResult:
    """Outcome of a single cascade-aware step.

    Captures both the initial run AND the escalation (if it happened)
    so the caller can show the full trace, not just the accepted
    output. `accepted_*` fields are whichever pair (initial vs
    escalation) is being passed downstream.
    """

    initial_model: str
    initial_output: str
    initial_confidence: int | None
    initial_cost: float
    initial_latency: float

    escalated: bool

    escalation_model: str | None = None
    escalation_output: str | None = None
    escalation_confidence: int | None = None
    escalation_cost: float | None = None
    escalation_latency: float | None = None

    accepted_output: str = ""
    accepted_model: str = ""
    accepted_confidence: int | None = None

    below_threshold: bool = False
    warning: str | None = None

    # Errors propagated from the underlying model_runner, if any.
    initial_error: str | None = None
    escalation_error: str | None = None


# ── Default model runner ─────────────────────────────────────────────
def _default_model_runner(model_name: str, prompt: str) -> dict:
    """Real-API model invocation. Returns a dict the router can consume.

    Constructs a fresh adapter on each call so the per-instance state
    (e.g. the GeminiFlash pacing timestamp) doesn't accumulate across
    requests on a long-lived router instance.
    """
    from models.anthropic_adapter import ClaudeHaiku
    from models.claude_opus_adapter import ClaudeOpus
    from models.gemini_adapter import GeminiFlash
    from models.gemini_flash_lite_adapter import GeminiFlashLite
    from models.gemini_pro_adapter import GeminiPro
    from models.gpt5_adapter import GPT5
    from models.o3_adapter import O3
    from models.openai_adapter import GPT4oMini

    adapters = {
        "claude-haiku-4-5": ClaudeHaiku,
        "claude-opus-4-7": ClaudeOpus,
        "gemini-2.5-flash": GeminiFlash,
        "gemini-2.5-flash-lite": GeminiFlashLite,
        "gemini-2.5-pro": GeminiPro,
        "gpt-4o-mini": GPT4oMini,
        "gpt-5": GPT5,
        "o3": O3,
    }
    cls = adapters.get(model_name)
    if cls is None:
        return {
            "output": "",
            "latency_ms": 0.0,
            "cost_usd": 0.0,
            "error": f"no adapter registered for model {model_name!r}",
        }

    adapter = cls()
    t0 = time.perf_counter()
    output = ""
    error: str | None = None
    try:
        output = adapter.generate(prompt)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - t0) * 1000

    rates = MODEL_COSTS.get(model_name, {"input": 0.0, "output": 0.0})
    in_tok = max(1, len(prompt) // 4)
    out_tok = max(1, len(output) // 4)
    cost_usd = in_tok * rates["input"] + out_tok * rates["output"]

    return {
        "output": output,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "error": error,
    }


# ── Router ───────────────────────────────────────────────────────────
class CascadeAwareRouter:
    """Wraps LookupTableRouter with runtime confidence-based escalation.

    Per `run_step`:
      1. LookupTableRouter picks the cheapest model meeting
         MIN_ACCEPTABLE_SCORE for the task.
      2. The model runs; the caller's parse_confidence reads the
         confidence from the output.
      3. If confidence >= escalation_threshold → accept, return.
      4. Otherwise pick the next-cheapest model with mean_score
         >= MIN_ACCEPTABLE_SCORE AND cost > initial cost.
      5. If no escalation candidate exists → accept initial,
         flag below_threshold with a warning.
      6. Re-run with escalation model. Use escalated output as
         accepted, regardless of whether its confidence is also low.
      7. If escalated confidence is still below threshold, flag
         below_threshold but do NOT escalate again. Maximum one
         escalation per step.
    """

    def __init__(
        self,
        lookup_router: LookupTableRouter | None = None,
        model_runner: Callable[[str, str], dict] | None = None,
        escalation_threshold: float = 7.0,
    ):
        self._lookup = (
            lookup_router if lookup_router is not None else LookupTableRouter()
        )
        self._model_runner = (
            model_runner if model_runner is not None else _default_model_runner
        )
        self._threshold = float(escalation_threshold)

    # ── Public ──────────────────────────────────────────────────────
    def run_step(
        self,
        prompt: str,
        task: str,
        parse_confidence: Callable[[str], int | None],
    ) -> CascadeResult:
        # 1. Pick initial model via the static router.
        decision = self._lookup.route(task)
        initial_model = decision.recommended_model

        # 2. Run with initial model.
        r1 = self._model_runner(initial_model, prompt)
        initial_output = r1.get("output", "")
        initial_latency = float(r1.get("latency_ms", 0.0))
        initial_cost = float(r1.get("cost_usd", 0.0))
        initial_error = r1.get("error")
        initial_confidence = parse_confidence(initial_output)

        # 3. Decide whether to escalate.
        confident_enough = (
            initial_confidence is not None
            and initial_confidence >= self._threshold
        )
        if confident_enough:
            return CascadeResult(
                initial_model=initial_model,
                initial_output=initial_output,
                initial_confidence=initial_confidence,
                initial_cost=initial_cost,
                initial_latency=initial_latency,
                escalated=False,
                accepted_output=initial_output,
                accepted_model=initial_model,
                accepted_confidence=initial_confidence,
                below_threshold=False,
                warning=None,
                initial_error=initial_error,
            )

        # 4. Pick escalation candidate.
        escalation_model = self._pick_escalation_model(task, initial_model)
        if escalation_model is None:
            warning = (
                f"Confidence {initial_confidence!s} on {initial_model} is below "
                f"threshold {self._threshold:.0f}, but no higher-tier model with "
                f"mean_score >= {MIN_ACCEPTABLE_SCORE} is available for {task}. "
                f"Consider human review."
            )
            return CascadeResult(
                initial_model=initial_model,
                initial_output=initial_output,
                initial_confidence=initial_confidence,
                initial_cost=initial_cost,
                initial_latency=initial_latency,
                escalated=False,
                accepted_output=initial_output,
                accepted_model=initial_model,
                accepted_confidence=initial_confidence,
                below_threshold=True,
                warning=warning,
                initial_error=initial_error,
            )

        # 5. Run escalation. Maximum one — never recurse.
        r2 = self._model_runner(escalation_model, prompt)
        escalation_output = r2.get("output", "")
        escalation_latency = float(r2.get("latency_ms", 0.0))
        escalation_cost = float(r2.get("cost_usd", 0.0))
        escalation_error = r2.get("error")
        escalation_confidence = parse_confidence(escalation_output)

        below_threshold = (
            escalation_confidence is None
            or escalation_confidence < self._threshold
        )
        warning = None
        if below_threshold:
            warning = (
                f"Escalated to {escalation_model} but confidence "
                f"{escalation_confidence!s} is still below threshold "
                f"{self._threshold:.0f}. Maximum one escalation per step; "
                f"consider human review."
            )

        return CascadeResult(
            initial_model=initial_model,
            initial_output=initial_output,
            initial_confidence=initial_confidence,
            initial_cost=initial_cost,
            initial_latency=initial_latency,
            escalated=True,
            escalation_model=escalation_model,
            escalation_output=escalation_output,
            escalation_confidence=escalation_confidence,
            escalation_cost=escalation_cost,
            escalation_latency=escalation_latency,
            accepted_output=escalation_output,
            accepted_model=escalation_model,
            accepted_confidence=escalation_confidence,
            below_threshold=below_threshold,
            warning=warning,
            initial_error=initial_error,
            escalation_error=escalation_error,
        )

    # ── Internal ────────────────────────────────────────────────────
    def _pick_escalation_model(
        self, task: str, initial_model: str
    ) -> str | None:
        """Cheapest model with mean_score >= MIN_ACCEPTABLE_SCORE and
        expected_cost_usd strictly greater than the initial pick. None
        if no such candidate exists.
        """
        rows = [r for r in self._lookup._matrix if r.get("task") == task]
        initial_row = next(
            (r for r in rows if r.get("model") == initial_model), None
        )
        initial_cost = (
            float(initial_row.get("expected_cost_usd", 0.0))
            if initial_row is not None
            else 0.0
        )
        candidates = [
            r for r in rows
            if float(r.get("mean_score", 0.0)) >= MIN_ACCEPTABLE_SCORE
            and float(r.get("expected_cost_usd", 0.0)) > initial_cost
        ]
        if not candidates:
            return None
        cheapest = min(
            candidates, key=lambda r: float(r.get("expected_cost_usd", 0.0))
        )
        return cheapest["model"]
