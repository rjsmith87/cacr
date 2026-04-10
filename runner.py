"""CACR — Cascade-Aware Confidence Routing: benchmark runner.

Loops every (task, model) pair, runs each example, times the call,
then asks the model for a self-reported confidence score (1-10).
Emits one JSON line per call to stdout.  After each pair finishes,
emits a summary with mean score, mean latency, pass/fail, and a
calibration metric (Pearson r between confidence and eval score).

Run:  python runner.py
"""

import json
import math
import os
import re
import sys
import time
import traceback
from typing import Iterable

from models.anthropic_adapter import ClaudeHaiku
from models.base import Model
from models.gemini_adapter import GeminiFlash
from models.gemini_pro_adapter import GeminiPro
from models.openai_adapter import GPT4oMini
from tasks.base import Task
from tasks.code_review import CodeReview
from tasks.code_summarization import CodeSummarization
from tasks.security_vuln import SecurityVuln


def _load_dotenv(path: str) -> None:
    """Tiny .env loader so we don't pull in python-dotenv."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and val:
                os.environ.setdefault(key, val)


def _emit(record: dict) -> None:
    """Write one JSON record to stdout, flushing immediately."""
    print(json.dumps(record, ensure_ascii=False), flush=True)


DEBUG = os.environ.get("DEBUG", "0") == "1"


def _debug(msg: str) -> None:
    """Print to stderr when DEBUG=1."""
    if DEBUG:
        print(msg, file=sys.stderr, flush=True)


CONFIDENCE_PROMPT = (
    "Rate your confidence in this answer from 1-10. "
    "Reply with just the number."
)


def _parse_confidence(raw: str) -> int | None:
    """Extract the first integer 1-10 from the model's confidence reply."""
    m = re.search(r"\b(10|[1-9])\b", raw)
    return int(m.group(1)) if m else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient.  Returns None if undefined."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx * sy)


def run(tasks: Iterable[Task], models: Iterable[Model]) -> None:
    for task in tasks:
        examples = task.examples()
        for model in models:
            scores: list[float] = []
            confidences: list[float] = []
            latencies_ms: list[float] = []

            for idx, example in enumerate(examples):
                prompt = task.prompt(example)
                t0 = time.perf_counter()
                error = None
                output = ""
                try:
                    output = model.generate(prompt)
                except Exception as exc:  # noqa: BLE001 — log and continue
                    error = f"{type(exc).__name__}: {exc}"
                latency_ms = (time.perf_counter() - t0) * 1000.0

                if error is None:
                    try:
                        score = task.eval(example, output)
                    except Exception as exc:  # noqa: BLE001
                        error = f"eval_error: {type(exc).__name__}: {exc}"
                        score = 0.0
                else:
                    score = 0.0

                # Confidence probe — second call to the same model.
                confidence_score: int | None = None
                if error is None:
                    conf_prompt = (
                        f"You were asked:\n{prompt}\n\n"
                        f"You answered:\n{output}\n\n"
                        f"{CONFIDENCE_PROMPT}"
                    )
                    try:
                        conf_raw = model.generate(conf_prompt)
                        confidence_score = _parse_confidence(conf_raw)
                        _debug(f"  CONFIDENCE RAW: {conf_raw!r} -> {confidence_score}")
                    except Exception as exc:  # noqa: BLE001
                        _debug(f"  CONFIDENCE ERROR: {exc}")

                _debug(
                    f"\n--- {task.name} | {model.name} | example {idx} ---\n"
                    f"PROMPT:\n{prompt}\n\n"
                    f"OUTPUT:\n{output}\n"
                    f"SCORE: {score}  CONFIDENCE: {confidence_score}  ERROR: {error}"
                )

                scores.append(score)
                confidences.append(float(confidence_score) if confidence_score is not None else float("nan"))
                latencies_ms.append(latency_ms)

                _emit({
                    "event": "call",
                    "task": task.name,
                    "family": task.family,
                    "complexity": task.complexity,
                    "model": model.name,
                    "tier": model.tier,
                    "example_idx": idx,
                    "latency_ms": round(latency_ms, 2),
                    "score": score,
                    "confidence_score": confidence_score,
                    "output": output,
                    "error": error,
                })

            mean_score = sum(scores) / len(scores) if scores else 0.0
            mean_latency = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

            # Filter NaN for calibration calc.
            valid = [(c, s) for c, s in zip(confidences, scores) if not math.isnan(c)]
            cal_r = _pearson([c for c, _ in valid], [s for _, s in valid]) if valid else None

            valid_confs = [c for c, _ in valid]
            mean_conf = sum(valid_confs) / len(valid_confs) if valid_confs else None

            _emit({
                "event": "summary",
                "task": task.name,
                "family": task.family,
                "complexity": task.complexity,
                "model": model.name,
                "tier": model.tier,
                "n": len(scores),
                "mean_score": round(mean_score, 4),
                "mean_confidence": round(mean_conf, 2) if mean_conf is not None else None,
                "calibration_r": round(cal_r, 4) if cal_r is not None else None,
                "mean_latency_ms": round(mean_latency, 2),
                "threshold": task.threshold,
                "passes_threshold": mean_score >= task.threshold,
                "cost_per_token": model.cost_per_token,
            })


def main() -> int:
    _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    tasks: list[Task] = [CodeReview(), SecurityVuln(), CodeSummarization()]

    models: list[Model] = []
    for cls in [ClaudeHaiku, GeminiFlash, GeminiPro, GPT4oMini]:
        try:
            models.append(cls())
        except Exception as exc:  # noqa: BLE001
            _emit({"event": "init_error", "model": cls.name, "error": f"{type(exc).__name__}: {exc}"})
            traceback.print_exc(file=sys.stderr)

    if not models:
        _emit({"event": "fatal", "error": "No models could be initialised."})
        return 1

    run(tasks, models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
