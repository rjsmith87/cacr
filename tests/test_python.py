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
