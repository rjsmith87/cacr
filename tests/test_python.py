"""Unit tests for pure functions and adapter init contracts."""

import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from runner import _pearson, _parse_confidence  # noqa: E402
from router.cascade_router import CascadeAwareRouter, CascadeResult  # noqa: E402
from router.complexity import infer_complexity  # noqa: E402
from router.policy import LookupTableRouter  # noqa: E402


# ── _pearson ──────────────────────────────────────────────────────

def test_pearson_perfect_positive():
    assert _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    assert _pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_pearson_zero_variance_returns_none():
    assert _pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_pearson_too_few_points_returns_none():
    assert _pearson([1.0], [2.0]) is None


# ── _parse_confidence ─────────────────────────────────────────────

def test_parse_confidence_plain_number():
    assert _parse_confidence("7") == 7


def test_parse_confidence_in_sentence():
    assert _parse_confidence("I would say 8 out of 10") == 8


def test_parse_confidence_ten():
    assert _parse_confidence("10") == 10


def test_parse_confidence_no_match():
    assert _parse_confidence("not sure") is None


# ── infer_complexity ──────────────────────────────────────────────

def test_complexity_easy_for_trivial_snippet():
    assert infer_complexity("x = 1\ny = 2\nprint(x + y)") == "easy"


def test_complexity_hard_for_dangerous_pattern():
    assert infer_complexity("import os\nos.system('rm -rf /')") == "hard"


def test_complexity_hard_for_eval():
    assert infer_complexity("result = eval(user_input)") == "hard"


def test_complexity_medium_for_moderate_control_flow():
    # ~35 LOC + 5 control-flow keywords → both LOC and CF vote medium.
    # LOC threshold for medium is now >=30 (was >=20); test fixture
    # bumped accordingly.
    body = "\n".join([f"v{i} = {i}" for i in range(30)])
    branches = "\n".join([f"if v{i} > 0: pass" for i in range(5)])
    assert infer_complexity(body + "\n" + branches) == "medium"


# ── adapter init failure paths ────────────────────────────────────

def test_claude_haiku_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from models.anthropic_adapter import ClaudeHaiku
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeHaiku()


def test_gemini_flash_lite_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from models.gemini_flash_lite_adapter import GeminiFlashLite
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GeminiFlashLite()


# ── CascadeAwareRouter ────────────────────────────────────────────

def _matrix_row(task: str, model: str, mean_score: float, expected_cost_usd: float) -> dict:
    """Minimal cost-matrix row with the fields LookupTableRouter.route() reads."""
    return {
        "task": task,
        "model": model,
        "mean_score": mean_score,
        "expected_cost_usd": expected_cost_usd,
        "passes_threshold": True,
    }


def _fake_lookup(matrix: list[dict]) -> LookupTableRouter:
    """Bypass __init__ (which tries to load cost_matrix.csv) and inject a
    fixture matrix directly so the routing decision is deterministic."""
    r = LookupTableRouter.__new__(LookupTableRouter)
    r._matrix = matrix
    return r


def _parse_conf(out: str) -> int | None:
    """Match the canonical 'confidence: N' format used by the pipelines."""
    import re
    m = re.search(r"confidence:\s*(\d+)", out or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


def test_cascade_escalates_when_confidence_below_threshold():
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        if model == "cheap":
            return {"output": "severity: high\nconfidence: 5", "latency_ms": 100, "cost_usd": 0.0001, "error": None}
        if model == "mid":
            return {"output": "severity: high\nconfidence: 9", "latency_ms": 200, "cost_usd": 0.001, "error": None}
        raise AssertionError(f"unexpected model {model}")

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
    )
    result = router.run_step("...prompt...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.initial_model == "cheap"
    assert result.initial_confidence == 5
    assert result.escalation_model == "mid"
    assert result.escalation_confidence == 9
    assert result.accepted_model == "mid"
    assert result.accepted_confidence == 9
    assert result.below_threshold is False
    assert result.warning is None
    assert runs == ["cheap", "mid"]


def test_cascade_does_not_escalate_when_confident():
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        return {"output": "severity: high\nconfidence: 9", "latency_ms": 100, "cost_usd": 0.0001, "error": None}

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is False
    assert result.escalation_model is None
    assert result.escalation_output is None
    assert result.escalation_confidence is None
    assert result.accepted_model == "cheap"
    assert result.accepted_confidence == 9
    assert result.below_threshold is False
    # No second call made.
    assert runs == ["cheap"]


def test_cascade_max_one_escalation_even_when_escalation_also_low():
    # Three models exist; even if both cheap AND mid return low
    # confidence, the router must NOT proceed to premium. Hard cap
    # of one escalation per step is the whole point.
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
        _matrix_row("SecurityVuln", "premium", 0.99, 0.01),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        if model == "cheap":
            return {"output": "severity: high\nconfidence: 5", "latency_ms": 100, "cost_usd": 0.0001, "error": None}
        if model == "mid":
            return {"output": "severity: high\nconfidence: 6", "latency_ms": 200, "cost_usd": 0.001, "error": None}
        if model == "premium":
            raise AssertionError("router escalated past 'mid' — should be capped at 1 escalation")
        raise AssertionError(f"unexpected model {model}")

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.escalation_model == "mid"
    assert result.below_threshold is True
    assert result.warning is not None
    assert "premium" not in (result.warning or "")
    assert runs == ["cheap", "mid"]
    assert len(runs) == 2


def test_cascade_accepted_output_is_escalation_output_when_escalated():
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]

    def runner(model: str, _prompt: str) -> dict:
        if model == "cheap":
            return {"output": "INITIAL_TEXT\nconfidence: 5", "latency_ms": 100, "cost_usd": 0.0001, "error": None}
        if model == "mid":
            return {"output": "ESCALATED_TEXT\nconfidence: 9", "latency_ms": 200, "cost_usd": 0.001, "error": None}
        raise AssertionError(f"unexpected model {model}")

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.initial_output == "INITIAL_TEXT\nconfidence: 5"
    assert result.escalation_output == "ESCALATED_TEXT\nconfidence: 9"
    # accepted_output is the escalation, not the initial:
    assert result.accepted_output == "ESCALATED_TEXT\nconfidence: 9"


def test_cascade_below_threshold_when_escalation_also_low():
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]

    def runner(model: str, _prompt: str) -> dict:
        # Both return low confidence — escalation runs but doesn't help.
        return {"output": "x\nconfidence: 4", "latency_ms": 100, "cost_usd": 0.0001, "error": None}

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.initial_confidence == 4
    assert result.escalation_confidence == 4
    assert result.accepted_confidence == 4
    assert result.below_threshold is True
    assert result.warning is not None
    assert "below threshold" in (result.warning or "").lower()


# ── Adapter logprob extraction (Phase 1: SLM tier) ────────────────
#
# Tests below patch the SDK clients with canned responses that mimic the
# real shape (per-token logprob entries, the avg_logprobs field, etc.)
# so we can exercise the aggregation helpers without making any live
# API calls. Defensive paths — missing fields, None values, empty lists
# — degrade to a no-signal GenerationResult, which the cascade router
# treats as "fall back to text-parsed self-report."

from types import SimpleNamespace  # noqa: E402

from models.base import GenerationResult  # noqa: E402


def _ns(**kw):
    """Shorthand for the deeply-nested SDK response shapes below."""
    return SimpleNamespace(**kw)


# ── OpenAI adapter ─────────────────────────────────────────────────

def _fake_openai_response(text: str, logprobs: list[float] | None):
    """Build a SimpleNamespace tree shaped like an openai SDK response."""
    if logprobs is None:
        logprobs_obj = None
    else:
        logprobs_obj = _ns(content=[_ns(logprob=lp) for lp in logprobs])
    return _ns(choices=[_ns(
        message=_ns(content=text),
        logprobs=logprobs_obj,
    )])


def test_openai_adapter_aggregates_logprobs(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from models.openai_adapter import GPT4oMini

    adapter = GPT4oMini()
    canned = _fake_openai_response(
        "severity: high\nconfidence: 8",
        [-0.1, -0.2, -0.3, -0.4],
    )

    class _FakeClient:
        def __init__(self):
            self.chat = _ns(completions=_ns(create=lambda **_: canned))

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert isinstance(result, GenerationResult)
    assert result.text == "severity: high\nconfidence: 8"
    assert result.logprob_mean == pytest.approx(-0.25)
    assert result.logprob_min == pytest.approx(-0.4)
    assert result.output_token_count == 4


def test_openai_adapter_handles_missing_logprobs(monkeypatch):
    """When logprobs come back None (older model, error path, etc.), the
    adapter must NOT raise — it returns a result with logprob fields
    None so the router falls back to self-report parsing."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from models.openai_adapter import GPT4oMini

    adapter = GPT4oMini()
    canned = _fake_openai_response("severity: high", logprobs=None)

    class _FakeClient:
        def __init__(self):
            self.chat = _ns(completions=_ns(create=lambda **_: canned))

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert result.text == "severity: high"
    assert result.logprob_mean is None
    assert result.logprob_min is None
    assert result.output_token_count == 0


def test_openai_adapter_handles_empty_logprob_content(monkeypatch):
    """logprobs object present but content list is empty → no signal."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from models.openai_adapter import GPT4oMini

    adapter = GPT4oMini()
    canned = _fake_openai_response("severity: high", logprobs=[])

    class _FakeClient:
        def __init__(self):
            self.chat = _ns(completions=_ns(create=lambda **_: canned))

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert result.logprob_mean is None
    assert result.output_token_count == 0


# ── Gemini adapters (Flash + Flash Lite) ───────────────────────────

def _fake_gemini_response(
    text: str,
    *,
    per_token: list[float] | None = None,
    server_avg: float | None = None,
):
    """Build a SimpleNamespace tree shaped like a google-genai response.
    Exercises both the per-token path and the server-computed avg path."""
    if per_token is None:
        logprobs_result = None
    else:
        logprobs_result = _ns(
            chosen_candidates=[_ns(log_probability=lp) for lp in per_token]
        )
    candidate = _ns(
        avg_logprobs=server_avg,
        logprobs_result=logprobs_result,
    )
    return _ns(candidates=[candidate], text=text)


def test_gemini_flash_aggregates_per_token_logprobs(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from models.gemini_adapter import GeminiFlash

    adapter = GeminiFlash()
    canned = _fake_gemini_response(
        "severity: high",
        per_token=[-0.1, -0.5, -0.2],
        server_avg=-0.2666,  # should be ignored when per-token is present
    )

    class _FakeClient:
        def __init__(self):
            self.models = _ns(generate_content=lambda **_: canned)

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert result.text == "severity: high"
    # Mean of [-0.1, -0.5, -0.2] = -0.2666...; per-token wins over server_avg.
    assert result.logprob_mean == pytest.approx(-0.2667, abs=1e-3)
    assert result.logprob_min == pytest.approx(-0.5)
    assert result.output_token_count == 3


def test_gemini_flash_falls_back_to_server_avg(monkeypatch):
    """When the SDK exposes only avg_logprobs (no per-token list), the
    adapter must use the server-computed mean and report
    output_token_count=0 to mark "no token-level data."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from models.gemini_adapter import GeminiFlash

    adapter = GeminiFlash()
    canned = _fake_gemini_response(
        "severity: high",
        per_token=None,
        server_avg=-0.4,
    )

    class _FakeClient:
        def __init__(self):
            self.models = _ns(generate_content=lambda **_: canned)

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert result.logprob_mean == pytest.approx(-0.4)
    assert result.logprob_min is None
    assert result.output_token_count == 0


def test_gemini_flash_handles_no_signal_at_all(monkeypatch):
    """No avg, no per-token, no candidate fields — graceful no-signal."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from models.gemini_adapter import GeminiFlash

    adapter = GeminiFlash()
    canned = _fake_gemini_response("severity: high", per_token=None, server_avg=None)

    class _FakeClient:
        def __init__(self):
            self.models = _ns(generate_content=lambda **_: canned)

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert result.logprob_mean is None
    assert result.logprob_min is None
    assert result.output_token_count == 0


def test_gemini_flash_lite_uses_same_aggregator(monkeypatch):
    """Flash Lite shares _aggregate_gemini_logprobs with Flash — sanity-
    check that the import path resolves and the structured call works."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from models.gemini_flash_lite_adapter import GeminiFlashLite

    adapter = GeminiFlashLite()
    canned = _fake_gemini_response(
        "vulnerable: yes",
        per_token=[-0.05, -0.15],
    )

    class _FakeClient:
        def __init__(self):
            self.models = _ns(generate_content=lambda **_: canned)

    adapter._client = _FakeClient()
    result = adapter.generate_structured("p")

    assert result.text == "vulnerable: yes"
    assert result.logprob_mean == pytest.approx(-0.1)
    assert result.logprob_min == pytest.approx(-0.15)
    assert result.output_token_count == 2


def test_default_generate_structured_is_no_signal():
    """An adapter that doesn't override generate_structured (Anthropic,
    o3, vertex) should inherit the base no-signal path — the router
    then falls back to self-report parsing."""
    from models.base import Model, GenerationResult

    class _Stub(Model):
        def generate(self, prompt: str) -> str:
            return "severity: low"

    result = _Stub().generate_structured("p")
    assert isinstance(result, GenerationResult)
    assert result.text == "severity: low"
    assert result.logprob_mean is None
    assert result.logprob_min is None
    assert result.output_token_count == 0


# ── CascadeAwareRouter — logprob-vs-self-report decision rule ──────
#
# The router prefers the logprob signal when present, falls back to the
# self-report integer when the adapter doesn't expose logprobs (Anthropic,
# o3, vertex), and treats "no signal at all" as below-threshold.

import math  # noqa: E402

from router.cascade_router import (  # noqa: E402
    _logprob_to_probability,
    DEFAULT_LOGPROB_THRESHOLD,
)


def test_logprob_to_probability_round_trip():
    # exp(log(p)) ≈ p for sane inputs; clamps at 1.0 for slightly
    # positive logprobs (which shouldn't happen in practice but
    # shouldn't crash the router either).
    assert _logprob_to_probability(None) is None
    assert _logprob_to_probability(0.0) == pytest.approx(1.0)
    assert _logprob_to_probability(math.log(0.5)) == pytest.approx(0.5)
    assert _logprob_to_probability(-1e6) == 0.0  # underflow → 0


def test_router_uses_logprob_when_above_threshold():
    """Logprob signal present and above threshold → accept, no escalation,
    confidence_signal='logprob' even though self-report says low."""
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        # Self-report says LOW but logprob says HIGH (probability ~0.95)
        # — this is the canonical Level 2 win: model wrote a low digit
        # but its actual token-distribution is confident.
        return {
            "output": "severity: high\nconfidence: 3",
            "latency_ms": 100,
            "cost_usd": 0.0001,
            "error": None,
            "logprob_mean": math.log(0.95),
            "logprob_min": math.log(0.90),
            "output_token_count": 4,
        }

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
        logprob_threshold=0.85,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is False
    assert result.accepted_model == "cheap"
    assert result.confidence_signal == "logprob"
    assert result.initial_logprob_confidence == pytest.approx(0.95, abs=1e-3)
    assert result.accepted_logprob_confidence == pytest.approx(0.95, abs=1e-3)
    # Self-report still recorded for telemetry / divergence study.
    assert result.initial_confidence == 3
    assert runs == ["cheap"]


def test_router_escalates_when_logprob_below_threshold_overriding_high_self_report():
    """Logprob is the source of truth: cheap model writes 'confidence: 9'
    but its token logprobs say probability=0.30. Escalate anyway —
    this is the overconfident-wrong failure mode Level 2 was built to
    catch."""
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        if model == "cheap":
            return {
                "output": "severity: high\nconfidence: 9",  # OVERCONFIDENT
                "latency_ms": 100,
                "cost_usd": 0.0001,
                "error": None,
                "logprob_mean": math.log(0.30),  # but logprob disagrees
                "logprob_min": math.log(0.10),
                "output_token_count": 6,
            }
        if model == "mid":
            return {
                "output": "severity: high\nconfidence: 9",
                "latency_ms": 200,
                "cost_usd": 0.001,
                "error": None,
                "logprob_mean": math.log(0.92),
                "logprob_min": math.log(0.80),
                "output_token_count": 6,
            }
        raise AssertionError(f"unexpected model {model}")

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
        logprob_threshold=0.85,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.initial_model == "cheap"
    assert result.escalation_model == "mid"
    assert result.confidence_signal == "logprob"
    assert result.initial_logprob_confidence == pytest.approx(0.30, abs=1e-3)
    assert result.escalation_logprob_confidence == pytest.approx(0.92, abs=1e-3)
    # Self-report was 9 on both — would have NEVER escalated under v1.
    assert result.initial_confidence == 9
    assert result.below_threshold is False
    assert runs == ["cheap", "mid"]


def test_router_falls_back_to_self_report_when_logprob_missing():
    """Adapter that doesn't override generate_structured (Anthropic, o3,
    vertex) → logprob_mean is None → router uses the self-report path
    with the legacy escalation_threshold."""
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        if model == "cheap":
            return {
                "output": "severity: high\nconfidence: 5",  # below 7
                "latency_ms": 100,
                "cost_usd": 0.0001,
                "error": None,
                "logprob_mean": None,  # no signal — Anthropic-style
                "logprob_min": None,
                "output_token_count": 0,
            }
        return {
            "output": "severity: high\nconfidence: 9",
            "latency_ms": 200,
            "cost_usd": 0.001,
            "error": None,
            "logprob_mean": None,
            "logprob_min": None,
            "output_token_count": 0,
        }

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
        logprob_threshold=0.85,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.confidence_signal == "self_report"
    assert result.initial_logprob_confidence is None
    assert result.escalation_logprob_confidence is None
    # Decision still works through the legacy 1-10 channel.
    assert result.initial_confidence == 5
    assert result.escalation_confidence == 9
    assert runs == ["cheap", "mid"]


def test_router_escalates_when_no_signal_at_all():
    """Both signals missing — model returned no parseable confidence
    AND adapter exposed no logprobs. Treat as below-threshold so we
    escalate (matches v1 'confidence is None' behavior)."""
    matrix = [
        _matrix_row("SecurityVuln", "cheap", 0.93, 0.0001),
        _matrix_row("SecurityVuln", "mid", 0.97, 0.001),
    ]
    runs: list[str] = []

    def runner(model: str, _prompt: str) -> dict:
        runs.append(model)
        return {
            "output": "severity: high",  # no 'confidence: N' line
            "latency_ms": 100,
            "cost_usd": 0.0001,
            "error": None,
            "logprob_mean": None,
            "logprob_min": None,
            "output_token_count": 0,
        }

    router = CascadeAwareRouter(
        lookup_router=_fake_lookup(matrix),
        model_runner=runner,
        escalation_threshold=7,
        logprob_threshold=0.85,
    )
    result = router.run_step("...", "SecurityVuln", _parse_conf)

    assert result.escalated is True
    assert result.confidence_signal == "none"
    assert result.initial_confidence is None
    assert result.initial_logprob_confidence is None


def test_router_default_logprob_threshold_is_documented_placeholder():
    """The 0.85 default is a placeholder pending calibration — guard
    against silent drift. If you change the constant, update the
    Level 2 calibration doc and bump this test."""
    assert DEFAULT_LOGPROB_THRESHOLD == 0.85
