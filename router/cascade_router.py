"""Cascade-aware router with runtime confidence-based escalation.

Layer 1 of cascade-aware routing: wraps the static LookupTableRouter
with a per-step escalation rule that fires when the cheapest passing
model returns a low-confidence answer. Maximum one escalation per
step — the router will not loop chasing confidence forever; if even
the escalated model is uncertain, it flags `below_threshold` and
proceeds.

Two confidence signals run in parallel as of Level 2:

  1. Self-reported confidence parsed from the model's text output
     (the legacy "confidence: 1-10" line). Compared against
     `escalation_threshold` (default 7.0). Available for every model.
  2. Mean per-token log-probability lifted from the adapter's
     structured generation call (OpenAI logprobs, Gemini
     response_logprobs). Compared against `logprob_threshold`
     (default 0.85, expressed in probability space). Available only
     on adapters that override `generate_structured` — currently
     GPT-4o-mini, Gemini Flash, Gemini Flash Lite. Anthropic, o3, and
     legacy Vertex adapters return None and the router falls back to
     signal #1.

When both signals are available the router prefers the logprob path
because the self-report digit is the very signal whose unreliability
on cheap-tier models motivated Level 2 in the first place. Both
values are recorded on CascadeResult for telemetry / divergence
study on the Confidence Accuracy tab.

The CascadeAwareRouter is intentionally pure logic: it does not
construct adapters itself, it does not parse model output, and it
does not know what a "step" means at the pipeline level. It accepts
a model_runner callable and a parse_confidence callable as
dependencies, which makes it trivial to unit-test with mocked
models. The default model_runner instantiates fresh adapters from
the existing models/ package on each call.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from router.cost_model import MODEL_COSTS
from router.policy import LookupTableRouter, MIN_ACCEPTABLE_SCORE


# Default mean per-token probability above which we accept the model's
# answer without escalation. Placeholder pending calibration against the
# benchmark battery — a real value comes from running the existing
# benchmark suite, plotting logprob distribution by score, and picking
# the threshold that maximizes correct-acceptance vs incorrect-
# acceptance separation. See docs/level2_calibration.md (TBD).
# Calibrated 2026-05-06 against 90 GPT-4o-mini calls (30 per task:
# CodeReview, SecurityVuln, CodeSummarization). Youden's J = 0.643
# at tau=0.96 (TPR=0.862, FPR=0.219). GPT-4o-mini only — Gemini
# logprobs unavailable on 2.5 series. Recalibrate when Gemini
# logprob support is added.
DEFAULT_LOGPROB_THRESHOLD = 0.96


@dataclass
class CascadeResult:
    """Outcome of a single cascade-aware step.

    Captures both the initial run AND the escalation (if it happened)
    so the caller can show the full trace, not just the accepted
    output. `accepted_*` fields are whichever pair (initial vs
    escalation) is being passed downstream.

    Two parallel confidence channels:
      - `*_confidence`: self-reported integer 1-10 parsed from the
        model's free-text output via the caller-supplied
        parse_confidence callable. Available for every model.
      - `*_logprob_confidence`: mean per-token probability in (0,1]
        derived from the adapter's structured generation call.
        Available only on adapters that override generate_structured.

    `confidence_signal` records which channel actually drove the
    accept/escalate decision: "logprob" when logprob data was
    available and used, "self_report" when we fell back to the
    parsed integer, "none" when neither signal was present.
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

    # Level 2: parallel logprob-based confidence channel. None on adapters
    # that don't expose token logprobs (Anthropic, o3, vertex). Each value
    # is `exp(mean_logprob)` — i.e. the geometric-mean per-token probability
    # in (0,1]. Higher = more confident.
    initial_logprob_confidence: float | None = None
    escalation_logprob_confidence: float | None = None
    accepted_logprob_confidence: float | None = None

    # Which channel drove the decision: "logprob" | "self_report" | "none".
    # Useful for telemetry — lets us measure how often each signal fires
    # and where the two disagree.
    confidence_signal: str = "none"


# Adapter location map: model name → (module path, class name). Used by
# `_default_model_runner` to import only the adapter that's actually
# needed per call. Importing all 8 eagerly pulls anthropic + openai +
# google-genai SDKs at once (~250-300 MB resident on Render Starter),
# which leaves no headroom for per-request response buffers and
# triggers gunicorn OOM kills during ssl.recv. Loading just-in-time
# means a Flash + Flash Lite + GPT-4o-mini request only pays for
# google-genai + openai, never the others.
_ADAPTER_MAP: dict[str, tuple[str, str]] = {
    "claude-haiku-4-5":      ("models.anthropic_adapter", "ClaudeHaiku"),
    "claude-opus-4-7":       ("models.claude_opus_adapter", "ClaudeOpus"),
    "gemini-2.5-flash":      ("models.gemini_adapter", "GeminiFlash"),
    "gemini-2.5-flash-lite": ("models.gemini_flash_lite_adapter", "GeminiFlashLite"),
    "gemini-2.5-pro":        ("models.gemini_pro_adapter", "GeminiPro"),
    "gpt-4o-mini":           ("models.openai_adapter", "GPT4oMini"),
    "gpt-5":                 ("models.gpt5_adapter", "GPT5"),
    "o3":                    ("models.o3_adapter", "O3"),
}


def _resolve_adapter_cls(model_name: str):
    """Just-in-time import of the adapter class for `model_name`.
    Python caches the import in sys.modules, so subsequent calls for
    the same model are free."""
    spec = _ADAPTER_MAP.get(model_name)
    if spec is None:
        return None
    import importlib
    mod_path, cls_name = spec
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name, None)


# ── Default model runner ─────────────────────────────────────────────
def _default_model_runner(model_name: str, prompt: str) -> dict:
    """Real-API model invocation. Returns a dict the router can consume.

    Constructs a fresh adapter on each call so the per-instance state
    (e.g. the GeminiFlash pacing timestamp) doesn't accumulate across
    requests on a long-lived router instance. The adapter class is
    looked up via just-in-time import (see `_resolve_adapter_cls`) so
    only the SDKs for the models actually used in the request get
    loaded — keeps memory footprint bounded on memory-constrained
    deploys.

    Always calls `adapter.generate_structured` (not `generate`). For
    adapters without a logprob override, `generate_structured` falls
    back through the base-class default to `generate` and returns a
    GenerationResult with logprob fields set to None — the router
    treats that as "no logprob signal, fall back to self-report."
    """
    cls = _resolve_adapter_cls(model_name)
    if cls is None:
        return {
            "output": "",
            "latency_ms": 0.0,
            "cost_usd": 0.0,
            "error": f"no adapter registered for model {model_name!r}",
            "logprob_mean": None,
            "logprob_min": None,
            "output_token_count": 0,
        }

    adapter = cls()
    t0 = time.perf_counter()
    output = ""
    error: str | None = None
    logprob_mean: float | None = None
    logprob_min: float | None = None
    token_count = 0
    try:
        result = adapter.generate_structured(prompt)
        output = result.text
        logprob_mean = result.logprob_mean
        logprob_min = result.logprob_min
        token_count = result.output_token_count
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
        "logprob_mean": logprob_mean,
        "logprob_min": logprob_min,
        "output_token_count": token_count,
    }


def _logprob_to_probability(logprob_mean: float | None) -> float | None:
    """Convert a mean log-probability to a mean probability in (0,1].
    Returns None passthrough so callers can use a single None check
    to detect "no signal."
    """
    if logprob_mean is None:
        return None
    # Clamp at 0.0 to be safe against any pathological input — exp(very
    # negative) underflows to 0.0 already, but a floor here makes the
    # contract explicit.
    return max(0.0, min(1.0, math.exp(logprob_mean)))


# ── Router ───────────────────────────────────────────────────────────
class CascadeAwareRouter:
    """Wraps LookupTableRouter with runtime confidence-based escalation.

    Per `run_step`:
      1. LookupTableRouter picks the cheapest model meeting
         MIN_ACCEPTABLE_SCORE for the task.
      2. The model runs; both signals are captured if available
         (logprob from the adapter, self-report from the text).
      3. If the preferred signal clears its threshold → accept, return.
         Logprob is preferred when present; fall back to self-report
         otherwise.
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
        logprob_threshold: float = DEFAULT_LOGPROB_THRESHOLD,
    ):
        self._lookup = (
            lookup_router if lookup_router is not None else LookupTableRouter()
        )
        self._model_runner = (
            model_runner if model_runner is not None else _default_model_runner
        )
        self._threshold = float(escalation_threshold)
        self._logprob_threshold = float(logprob_threshold)

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
        initial_logprob_conf = _logprob_to_probability(r1.get("logprob_mean"))

        # 3. Decide whether to escalate. Logprob signal is preferred when
        #    present; falls back to self-report when None.
        confident_enough, signal = self._is_confident_enough(
            initial_logprob_conf, initial_confidence
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
                initial_logprob_confidence=initial_logprob_conf,
                accepted_logprob_confidence=initial_logprob_conf,
                confidence_signal=signal,
            )

        # 4. Pick escalation candidate.
        escalation_model = self._pick_escalation_model(task, initial_model)
        if escalation_model is None:
            warning = (
                f"Confidence below threshold on {initial_model} "
                f"(self_report={initial_confidence!s}, "
                f"logprob={initial_logprob_conf!s}); no higher-tier model "
                f"with mean_score >= {MIN_ACCEPTABLE_SCORE} available for "
                f"{task}. Consider human review."
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
                initial_logprob_confidence=initial_logprob_conf,
                accepted_logprob_confidence=initial_logprob_conf,
                confidence_signal=signal,
            )

        # 5. Run escalation. Maximum one — never recurse.
        r2 = self._model_runner(escalation_model, prompt)
        escalation_output = r2.get("output", "")
        escalation_latency = float(r2.get("latency_ms", 0.0))
        escalation_cost = float(r2.get("cost_usd", 0.0))
        escalation_error = r2.get("error")
        escalation_confidence = parse_confidence(escalation_output)
        escalation_logprob_conf = _logprob_to_probability(r2.get("logprob_mean"))

        # 6. Did the escalation clear the bar? Same preference order:
        #    logprob if available, else self-report. Used only to set
        #    the below_threshold flag — the escalated output is accepted
        #    regardless (max-one-escalation hard cap).
        esc_confident, esc_signal = self._is_confident_enough(
            escalation_logprob_conf, escalation_confidence
        )
        below_threshold = not esc_confident
        warning = None
        if below_threshold:
            warning = (
                f"Escalated to {escalation_model} but confidence still below "
                f"threshold (self_report={escalation_confidence!s}, "
                f"logprob={escalation_logprob_conf!s}). Maximum one "
                f"escalation per step; consider human review."
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
            initial_logprob_confidence=initial_logprob_conf,
            escalation_logprob_confidence=escalation_logprob_conf,
            accepted_logprob_confidence=escalation_logprob_conf,
            # The escalation decision was driven by the initial step's
            # signal; report that one. The escalation's own signal is
            # captured separately on escalation_logprob_confidence.
            confidence_signal=signal,
        )

    # ── Internal ────────────────────────────────────────────────────
    def _is_confident_enough(
        self,
        logprob_conf: float | None,
        self_report: int | None,
    ) -> tuple[bool, str]:
        """Apply the preference policy: logprob signal wins when present.

        Returns (confident_enough, signal_used) where signal_used is one
        of "logprob" / "self_report" / "none". The "none" branch (both
        signals missing) treats the answer as below threshold so the
        router escalates — matches the v1 behavior of `confidence is None
        → escalate`.
        """
        if logprob_conf is not None:
            return logprob_conf >= self._logprob_threshold, "logprob"
        if self_report is not None:
            return self_report >= self._threshold, "self_report"
        return False, "none"

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
