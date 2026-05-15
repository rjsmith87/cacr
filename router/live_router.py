"""Live routing service — pick a model and actually call it.

The existing `/api/route` returns a routing DECISION (which model would
be picked + reasoning) but never invokes the chosen model. This module
closes that loop: classify the task's complexity, pick the cheapest
model meeting the accuracy floor for the task type, call its API, and
cascade to the next cheapest qualifying model if the response's
confidence is below the escalation threshold.

Built on the existing primitives:
  - `router.complexity.infer_complexity` — informational complexity tag.
  - `router.cascade_router.CascadeAwareRouter` — already encapsulates
    "pick cheapest passing → run → max-one-escalation on low
    confidence." We reuse it directly rather than re-implementing.
  - `pipelines.cascade_pipeline.parse_confidence` — parses the
    `confidence: N` line we coax out of the model.

The free-form user task is wrapped with an instruction to emit a
`confidence: N` line so the cascade router has a self-report signal
to inspect. Adapters that expose token logprobs (OpenAI, Gemini) still
contribute their logprob-derived confidence in parallel; the router
prefers logprobs when present.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Callable

from pipelines.cascade_pipeline import parse_confidence
from router.cascade_router import (
    CascadeAwareRouter,
    _default_model_runner,
    _logprob_to_probability,
)
from router.complexity import infer_complexity
from router.cost_model import MODEL_COSTS


# Appended to every routed task so the model emits a parseable
# self-reported confidence. Kept terse so it doesn't dominate the
# user's prompt; placed after a separator so the model sees it as
# meta-instruction rather than part of the task.
_CONFIDENCE_INSTRUCTION = (
    "\n\n---\n"
    "After your answer, write a final line in EXACTLY this format:\n"
    "confidence: N\n"
    "where N is an integer from 1 to 10 reflecting how confident you are "
    "in the answer (10 = certain, 1 = pure guess)."
)


def _wrap_with_confidence_request(task: str) -> str:
    return task + _CONFIDENCE_INSTRUCTION


@dataclass
class LiveRouteResponse:
    """Shape returned to API callers. Matches the user-facing spec
    (`response`, `model_used`, `cascaded`, `cost_estimate`,
    `latency_ms`) and adds enough trace detail for the dashboard to
    show what actually happened (initial pick, escalation, signal)."""

    response: str
    model_used: str
    cascaded: bool
    cost_estimate: float
    latency_ms: float
    task_type: str
    complexity: str
    confidence: int | None
    confidence_signal: str
    initial_model: str
    initial_confidence: int | None
    initial_cost: float
    initial_latency: float
    escalation_model: str | None
    escalation_confidence: int | None
    escalation_cost: float | None
    escalation_latency: float | None
    below_threshold: bool
    warning: str | None
    error: str | None


def route_and_run(
    task: str,
    task_type: str,
    escalation_threshold: float = 7.0,
    model_runner: Callable[[str, str], dict] | None = None,
) -> LiveRouteResponse:
    """Route a single task to its cost-optimal model and call it.

    `model_runner` is injectable for tests so the function can be
    exercised without hitting paid APIs.
    """
    runner = model_runner if model_runner is not None else _default_model_runner
    complexity = infer_complexity(task)

    # Consult the static router first so we can preserve its
    # below_threshold / warning signal when no model passes the global
    # accuracy floor (e.g. CodeSummarization in the current matrix).
    # The cascade router below picks the same model but discards this
    # signal whenever runtime confidence happens to be high — and the
    # overconfident-wrong case is exactly what the floor warning
    # exists to flag.
    from router.policy import LookupTableRouter
    static_decision = LookupTableRouter().route(task_type)

    router = CascadeAwareRouter(
        model_runner=runner,
        escalation_threshold=escalation_threshold,
    )
    prompt = _wrap_with_confidence_request(task)
    result = router.run_step(prompt, task_type, parse_confidence)

    total_cost = float(result.initial_cost) + float(result.escalation_cost or 0.0)
    total_latency = float(result.initial_latency) + float(result.escalation_latency or 0.0)
    error = result.initial_error or result.escalation_error

    # below_threshold is the OR of (cascade-runtime confidence too low)
    # and (no model passes the static floor for this task). Same for
    # the warning text — the static warning is more informative when
    # both fire because it names the underlying capability gap.
    below_threshold = result.below_threshold or static_decision.below_threshold
    warning = static_decision.warning if static_decision.below_threshold else result.warning

    return LiveRouteResponse(
        response=result.accepted_output,
        model_used=result.accepted_model,
        cascaded=result.escalated,
        cost_estimate=round(total_cost, 8),
        latency_ms=round(total_latency, 1),
        task_type=task_type,
        complexity=complexity,
        confidence=result.accepted_confidence,
        confidence_signal=result.confidence_signal,
        initial_model=result.initial_model,
        initial_confidence=result.initial_confidence,
        initial_cost=round(float(result.initial_cost), 8),
        initial_latency=round(float(result.initial_latency), 1),
        escalation_model=result.escalation_model,
        escalation_confidence=result.escalation_confidence,
        escalation_cost=(
            round(float(result.escalation_cost), 8)
            if result.escalation_cost is not None else None
        ),
        escalation_latency=(
            round(float(result.escalation_latency), 1)
            if result.escalation_latency is not None else None
        ),
        below_threshold=below_threshold,
        warning=warning,
        error=error,
    )


def compare_all_models(
    task: str,
    task_type: str,
    escalation_threshold: float = 7.0,
    model_runner: Callable[[str, str], dict] | None = None,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Run the same task through every model in MODEL_COSTS so the
    caller can see what the router's pick is missing (or saving).

    Returns a dict with per-model results AND the routing decision the
    LookupTableRouter would have made for this task_type. We avoid a
    9th API call by reading the picked model's row out of the per-model
    results we already computed.

    Calls fan out across a small thread pool because each model is an
    independent network call (~1-5 s). Concurrency is capped at 4 to
    keep memory bounded on the 2 GB Render Standard plan — each
    adapter holds an SDK client + a connection pool, and the cascade
    pipeline's own JIT-import pattern already established this as the
    practical ceiling.
    """
    runner = model_runner if model_runner is not None else _default_model_runner
    prompt = _wrap_with_confidence_request(task)

    def _call(model_name: str) -> dict[str, Any]:
        r = runner(model_name, prompt)
        text = r.get("output", "") or ""
        return {
            "model": model_name,
            "response": text,
            "confidence": parse_confidence(text),
            "logprob_confidence": _logprob_to_probability(r.get("logprob_mean")),
            "cost_usd": round(float(r.get("cost_usd", 0.0)), 8),
            "latency_ms": round(float(r.get("latency_ms", 0.0)), 1),
            "error": r.get("error"),
        }

    models = list(MODEL_COSTS.keys())
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        per_model = list(pool.map(_call, models))

    # Determine what the router would have picked for this task_type.
    # Imported lazily to keep the module loadable in test environments
    # that haven't populated cost_matrix.csv.
    from router.policy import LookupTableRouter
    decision = LookupTableRouter().route(task_type)
    routed_model = decision.recommended_model
    routed_entry = next((r for r in per_model if r["model"] == routed_model), None)
    total_cost_all = sum(r["cost_usd"] for r in per_model)
    routed_cost = routed_entry["cost_usd"] if routed_entry else 0.0

    return {
        "task_type": task_type,
        "complexity": infer_complexity(task),
        "routed_model": routed_model,
        "routed_cost_estimate": routed_entry["cost_usd"] if routed_entry else None,
        "routed_response": routed_entry["response"] if routed_entry else None,
        "routed_reasoning": decision.reasoning,
        "routed_below_threshold": decision.below_threshold,
        "routed_warning": decision.warning,
        "total_cost_if_all_models_run": round(total_cost_all, 8),
        "cost_saved_vs_running_all": round(total_cost_all - routed_cost, 8),
        # Sorted cheapest → most expensive so the dashboard can render
        # the row order without re-sorting client-side.
        "results": sorted(per_model, key=lambda r: r["cost_usd"]),
    }


def as_dict(resp: LiveRouteResponse) -> dict[str, Any]:
    """JSON-serializable dict form of a LiveRouteResponse."""
    return asdict(resp)
