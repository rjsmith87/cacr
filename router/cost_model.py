"""Cascade cost model for CACR.

For each (task, model) pair, computes:
  expected_cost = (cost_per_token × mean_tokens) × P(success)
                + retry_cost × P(failure) × cascade_depth

Where cascade_depth=3 (our pipeline length) and retry_cost = cost of
one Haiku call as fallback.

Reads from BigQuery benchmark_summaries or accepts data directly.
Outputs a cost matrix as a Python dict and CSV.
"""

import csv
import json
import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

CASCADE_DEPTH = 3
MEAN_PROMPT_TOKENS = 200  # rough average across our task battery
MEAN_OUTPUT_TOKENS = 30

# Per-model input/output pricing in USD per token. List prices as of
# 2026-Q1. Reasoning tokens (o3, GPT-5, Gemini 2.5 Pro) bill at the
# output rate — when actual call records expose reasoning_tokens, add
# them to the visible output token count before pricing.
MODEL_COSTS = {
    "claude-haiku-4-5":      {"input": 1.0e-6,  "output": 5.0e-6},
    "claude-opus-4-7":       {"input": 1.5e-5,  "output": 7.5e-5},
    "gemini-2.5-flash":      {"input": 3.0e-7,  "output": 2.5e-6},
    "gemini-2.5-flash-lite": {"input": 1.0e-7,  "output": 4.0e-7},
    "gemini-2.5-pro":        {"input": 1.25e-6, "output": 1.0e-5},
    "gpt-4o-mini":           {"input": 1.5e-7,  "output": 6.0e-7},
    "gpt-5":                 {"input": 1.25e-6, "output": 1.0e-5},
    "o3":                    {"input": 2.0e-6,  "output": 8.0e-6},
}

HAIKU_RETRY_COST = (
    MEAN_PROMPT_TOKENS * MODEL_COSTS["claude-haiku-4-5"]["input"]
    + MEAN_OUTPUT_TOKENS * MODEL_COSTS["claude-haiku-4-5"]["output"]
)


def _rates_for(model: str, fallback_input: float = 1e-6) -> tuple[float, float]:
    """Look up (input, output) rates for a model, with backward-compat fallback.

    Legacy callers and BQ rows may only carry a single `cost_per_token`
    value (the input rate). For models we don't have explicit pricing
    for, approximate output as 4× input — matches the Haiku/Sonnet/4o
    markup pattern. Real frontier models (Opus, Pro) have 5–8× output
    markups so they should always be in MODEL_COSTS.
    """
    rates = MODEL_COSTS.get(model)
    if rates:
        return rates["input"], rates["output"]
    return fallback_input, fallback_input * 4.0


def compute_expected_cost(
    input_cost: float,
    output_cost: float,
    mean_score: float,
    cascade_depth: int = CASCADE_DEPTH,
    retry_cost: float = HAIKU_RETRY_COST,
    mean_input_tokens: int = MEAN_PROMPT_TOKENS,
    mean_output_tokens: int = MEAN_OUTPUT_TOKENS,
) -> float:
    """Expected cost including cascade failure retry.

    `input_cost` / `output_cost` are USD per token. When pricing
    reasoning models, callers should fold reasoning tokens into
    `mean_output_tokens` before calling.
    """
    p_success = mean_score
    p_failure = 1.0 - p_success
    base_cost = (
        input_cost * mean_input_tokens
        + output_cost * mean_output_tokens
    ) * p_success
    failure_cost = retry_cost * p_failure * cascade_depth
    return base_cost + failure_cost


def build_cost_matrix_from_bq(project: str) -> list[dict[str, Any]]:
    """Query BigQuery for latest benchmark summaries and build cost matrix."""
    from google.cloud import bigquery
    client = bigquery.Client(project=project)

    query = """
    SELECT task, model, tier, mean_score, cost_per_token,
           calibration_r, mean_latency_ms, passes_threshold,
           calibration_by_difficulty
    FROM `cacr_results.benchmark_summaries`
    WHERE run_ts = (SELECT MAX(run_ts) FROM `cacr_results.benchmark_summaries`)
    ORDER BY task, cost_per_token
    """
    rows = list(client.query(query).result())
    return _build_matrix([dict(r) for r in rows])


def build_cost_matrix_from_jsonl(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build cost matrix from runner JSONL summary records."""
    summaries = [r for r in lines if r.get("event") == "summary"]
    return _build_matrix(summaries)


def _build_matrix(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = []
    for row in summaries:
        task = row.get("task", "")
        model = row.get("model", "")
        score = row.get("mean_score", 0.0)
        # Prefer the explicit input/output split from MODEL_COSTS;
        # fall back to the legacy per-row cost_per_token (treated as
        # the input rate, with output approximated at 4×).
        legacy_cpt = row.get("cost_per_token") or 0
        input_cost, output_cost = _rates_for(
            model, fallback_input=legacy_cpt or 1e-6
        )
        cal_r = row.get("calibration_r")
        latency = row.get("mean_latency_ms", 0)
        passes = row.get("passes_threshold", False)

        exp_cost = compute_expected_cost(input_cost, output_cost, score)
        # Score/cost ratio (higher = better value)
        sc_ratio = score / (exp_cost * 1e6) if exp_cost > 0 else 0

        matrix.append({
            "task": task,
            "model": model,
            "tier": row.get("tier"),
            "mean_score": score,
            "cost_per_token": input_cost,
            "input_cost_per_token": input_cost,
            "output_cost_per_token": output_cost,
            "expected_cost_usd": round(exp_cost, 10),
            "score_cost_ratio": round(sc_ratio, 2),
            "calibration_r": cal_r,
            "mean_latency_ms": latency,
            "passes_threshold": passes,
            "is_cost_optimal": False,  # filled below
        })

    # Mark cost-optimal model per task (cheapest that passes threshold)
    by_task: dict[str, list[dict]] = {}
    for entry in matrix:
        by_task.setdefault(entry["task"], []).append(entry)

    for task, entries in by_task.items():
        passing = [e for e in entries if e["passes_threshold"]]
        if passing:
            best = min(passing, key=lambda e: e["expected_cost_usd"])
            best["is_cost_optimal"] = True

    return matrix


def write_csv(matrix: list[dict[str, Any]], path: str) -> None:
    if not matrix:
        return
    fields = list(matrix[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(matrix)


def print_matrix(matrix: list[dict[str, Any]]) -> None:
    print(f"\n{'Task':22s} {'Model':22s} {'Score':>6s} {'ExpCost($)':>12s} {'$/Score':>10s} {'Cal_r':>7s} {'Lat(ms)':>8s} {'Pass':>5s} {'Opt':>4s}")
    print("-" * 100)
    for e in matrix:
        cal = f"{e['calibration_r']:+.3f}" if e['calibration_r'] is not None else "N/A"
        opt = "*" if e["is_cost_optimal"] else ""
        print(
            f"{e['task']:22s} {e['model']:22s} {e['mean_score']:6.2f} "
            f"{e['expected_cost_usd']:12.8f} {e['score_cost_ratio']:10.1f} "
            f"{cal:>7s} {e['mean_latency_ms']:8.0f} "
            f"{'Y' if e['passes_threshold'] else 'N':>5s} {opt:>4s}"
        )


def main() -> int:
    project = os.environ.get("GCP_PROJECT")

    # Try BQ first, fall back to reading stdin
    matrix = None
    if project:
        try:
            def _load_dotenv(path: str) -> None:
                if not os.path.exists(path):
                    return
                with open(path) as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and v:
                            os.environ.setdefault(k, v)

            _load_dotenv(os.path.join(_ROOT, ".env"))
            matrix = build_cost_matrix_from_bq(project)
        except Exception as exc:
            print(f"BQ query failed ({exc}), reading from stdin...", file=sys.stderr)

    if matrix is None:
        # Read JSONL from stdin
        lines = []
        for raw in sys.stdin:
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        matrix = build_cost_matrix_from_jsonl(lines)

    if not matrix:
        print("No data found.", file=sys.stderr)
        return 1

    csv_path = os.path.join(_ROOT, "results", "cost_matrix.csv")
    write_csv(matrix, csv_path)
    print_matrix(matrix)
    print(f"\nCSV written to {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
