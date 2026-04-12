"""Unit tests for pure functions and adapter init contracts."""

import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from runner import _pearson, _parse_confidence  # noqa: E402
from router.complexity import infer_complexity  # noqa: E402


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
    # ~25 LOC + 5 control-flow keywords → both LOC and CF vote medium.
    body = "\n".join([f"v{i} = {i}" for i in range(20)])
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
