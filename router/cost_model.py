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
HAIKU_COST_PER_TOKEN = 1.0e-6
MEAN_PROMPT_TOKENS = 200  # rough average across our task battery
MEAN_OUTPUT_TOKENS = 30
HAIKU_RETRY_COST = (MEAN_PROMPT_TOKENS + MEAN_OUTPUT_TOKENS) * HAIKU_COST_PER_TOKEN

# Model cost lookup
MODEL_COSTS = {
    "claude-haiku-4-5": 1.0e-6,
    "gemini-2.5-flash": 1.0e-7,
    "gemini-2.5-flash-lite": 4.0e-8,
    "gpt-4o-mini": 1.5e-7,
}


def compute_expected_cost(
    cost_per_token: float,
    mean_score: float,
    cascade_depth: int = CASCADE_DEPTH,
    retry_cost: float = HAIKU_RETRY_COST,
    mean_tokens: int = MEAN_PROMPT_TOKENS + MEAN_OUTPUT_TOKENS,
) -> float:
    """Expected cost including cascade failure retry."""
    p_success = mean_score
    p_failure = 1.0 - p_success
    base_cost = cost_per_token * mean_tokens * p_success
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
        cpt = row.get("cost_per_token", MODEL_COSTS.get(model, 0))
        cal_r = row.get("calibration_r")
        latency = row.get("mean_latency_ms", 0)
        passes = row.get("passes_threshold", False)

        exp_cost = compute_expected_cost(cpt, score)
        # Score/cost ratio (higher = better value)
        sc_ratio = score / (exp_cost * 1e6) if exp_cost > 0 else 0

        matrix.append({
            "task": task,
            "model": model,
            "tier": row.get("tier"),
            "mean_score": score,
            "cost_per_token": cpt,
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
