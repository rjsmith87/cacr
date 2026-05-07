"""Calibrate DEFAULT_LOGPROB_THRESHOLD from real benchmark distribution.

Queries cacr_results.benchmark_calls for rows where logprob_mean IS NOT
NULL (post-Phase-1 instrumentation). For each row, derives:
  - prob    = exp(logprob_mean)              # mean per-token probability
  - correct = score >= MIN_CORRECT           # whether the call was right

Sweeps τ ∈ [0.50, 0.99] and picks argmax Youden's J = TPR - FPR — the
threshold that best separates correct (we want to accept) from incorrect
(we want to escalate) outputs on this distribution.

Reports per-model + per-task sample sizes, distribution stats per group,
the full sweep table, and a per-model J check at the recommended τ so
you can see if the chosen threshold generalises across adapters or is
being driven by one model's distribution.

Usage:
  python scripts/calibrate_logprob_threshold.py
  python scripts/calibrate_logprob_threshold.py --min-correct 0.5
  python scripts/calibrate_logprob_threshold.py --since 2026-05-06
  python scripts/calibrate_logprob_threshold.py --jsonl results/run.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from typing import Iterable

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


def _load_dotenv() -> None:
    path = os.path.join(_ROOT, ".env")
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


def _fetch_from_bq(since: str | None) -> list[dict]:
    """Pull (model, task, score, logprob_mean) rows from benchmark_calls."""
    from results.bq_writer import _build_bq_client
    project = os.environ.get("GCP_PROJECT")
    if not project:
        sys.exit("GCP_PROJECT not set; aborting.")
    client = _build_bq_client(project)
    where_since = f"AND run_ts >= TIMESTAMP('{since}')" if since else ""
    sql = f"""
        SELECT model, task, difficulty, score, logprob_mean, output_token_count
        FROM `cacr_results.benchmark_calls`
        WHERE logprob_mean IS NOT NULL
          AND score IS NOT NULL
          {where_since}
    """
    return [dict(r) for r in client.query(sql).result()]


def _fetch_from_jsonl(path: str) -> list[dict]:
    """Read a JSONL fixture (alternative to BQ for offline analysis)."""
    rows = []
    with open(path) as f:
        for raw in f:
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if d.get("logprob_mean") is None or d.get("score") is None:
                continue
            rows.append(d)
    return rows


def _summarize(values: list[float]) -> dict:
    """Distribution stats — no numpy dep."""
    if not values:
        return {"n": 0}
    s = sorted(values)
    n = len(s)
    mean = sum(s) / n
    var = sum((v - mean) ** 2 for v in s) / n if n > 1 else 0.0
    return {
        "n": n,
        "mean": mean,
        "std": math.sqrt(var),
        "min": s[0],
        "p10": s[int(n * 0.10)],
        "p25": s[int(n * 0.25)],
        "p50": s[int(n * 0.50)],
        "p75": s[int(n * 0.75)],
        "p90": s[int(n * 0.90)],
        "max": s[-1],
    }


def _sweep(probs_correct: list[float], probs_incorrect: list[float],
           grid: Iterable[float]) -> list[dict]:
    """For each candidate τ, compute TPR / FPR / Youden's J."""
    nC, nI = len(probs_correct), len(probs_incorrect)
    out = []
    for tau in grid:
        tpr = sum(1 for p in probs_correct if p >= tau) / nC if nC else 0.0
        fpr = sum(1 for p in probs_incorrect if p >= tau) / nI if nI else 0.0
        out.append({"tau": tau, "tpr": tpr, "fpr": fpr, "j": tpr - fpr})
    return out


def main() -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-correct", type=float, default=0.5,
                    help="Score above which a call is correct (default 0.5).")
    ap.add_argument("--since", type=str, default=None,
                    help="Only include calls with run_ts >= this date "
                         "(YYYY-MM-DD). Useful to scope to a specific run.")
    ap.add_argument("--jsonl", type=str, default=None,
                    help="Read from a JSONL fixture instead of BigQuery.")
    args = ap.parse_args()

    raw = (_fetch_from_jsonl(args.jsonl) if args.jsonl
           else _fetch_from_bq(args.since))

    if not raw:
        print("No rows with logprob_mean IS NOT NULL found.")
        print("Run the benchmark battery against the SLM tier first; ensure")
        print("runner.py has been patched to capture the new field.")
        return 1

    enriched = []
    for r in raw:
        lp = r.get("logprob_mean")
        sc = r.get("score")
        if lp is None or sc is None:
            continue
        enriched.append({
            "model":   r.get("model", "?"),
            "task":    r.get("task", "?"),
            "prob":    math.exp(float(lp)),
            "correct": float(sc) >= args.min_correct,
        })

    n_total = len(enriched)
    n_correct = sum(1 for e in enriched if e["correct"])
    n_incorrect = n_total - n_correct

    print("=== Calibration sample summary ===")
    print(f"Source:                          {'JSONL' if args.jsonl else 'BigQuery'}")
    print(f"Total rows with logprob_mean:    {n_total}")
    print(f"  Correct (score >= {args.min_correct}):     {n_correct}")
    print(f"  Incorrect:                     {n_incorrect}")

    if n_correct == 0 or n_incorrect == 0:
        print("\nERROR: need both classes to compute Youden's J. "
              "Adjust --min-correct or rerun benchmarks.")
        return 2

    by_model = Counter(e["model"] for e in enriched)
    by_task = Counter(e["task"] for e in enriched)

    print("\nPer model:")
    for model, n in sorted(by_model.items(), key=lambda kv: -kv[1]):
        nc = sum(1 for e in enriched if e["model"] == model and e["correct"])
        print(f"  {model:24} n={n:4} ({nc} correct, {n - nc} incorrect)")

    print("\nPer task:")
    for task, n in sorted(by_task.items(), key=lambda kv: -kv[1]):
        nc = sum(1 for e in enriched if e["task"] == task and e["correct"])
        print(f"  {task:24} n={n:4} ({nc} correct, {n - nc} incorrect)")

    probs_correct = [e["prob"] for e in enriched if e["correct"]]
    probs_incorrect = [e["prob"] for e in enriched if not e["correct"]]
    sC = _summarize(probs_correct)
    sI = _summarize(probs_incorrect)

    print("\n=== Probability distribution (mean per-token probability) ===")
    print(f"{'':10} {'Correct':>14} {'Incorrect':>14}")
    for k in ("n", "mean", "std", "min", "p10", "p25", "p50", "p75", "p90", "max"):
        cv, iv = sC.get(k, ""), sI.get(k, "")
        cs = f"{cv:.4f}" if isinstance(cv, float) else str(cv)
        is_ = f"{iv:.4f}" if isinstance(iv, float) else str(iv)
        print(f"{k:10} {cs:>14} {is_:>14}")

    grid = [0.50 + 0.01 * i for i in range(50)]   # 0.50 -> 0.99 inclusive
    sweep = _sweep(probs_correct, probs_incorrect, grid)
    best = max(sweep, key=lambda r: r["j"])

    print("\n=== Threshold sweep (Youden's J = TPR - FPR) ===")
    print(f"{'tau':>6} {'TPR':>8} {'FPR':>8} {'J':>8}")
    for row in sweep:
        marker = "  <-- argmax J" if row is best else ""
        print(f"{row['tau']:>6.2f} {row['tpr']:>8.4f} "
              f"{row['fpr']:>8.4f} {row['j']:>8.4f}{marker}")

    print(f"\n=== Per-model J at recommended tau={best['tau']:.2f} ===")
    print("(Sanity check: is one model dragging the threshold?)")
    for model in sorted(by_model.keys()):
        m_correct = [e["prob"] for e in enriched
                     if e["model"] == model and e["correct"]]
        m_incorrect = [e["prob"] for e in enriched
                       if e["model"] == model and not e["correct"]]
        if not m_correct or not m_incorrect:
            print(f"  {model:24} insufficient class balance")
            continue
        tpr = sum(1 for p in m_correct if p >= best["tau"]) / len(m_correct)
        fpr = sum(1 for p in m_incorrect if p >= best["tau"]) / len(m_incorrect)
        print(f"  {model:24} TPR={tpr:.3f} FPR={fpr:.3f} J={tpr-fpr:.3f}")

    print("\n=== Recommended ===")
    print(f"DEFAULT_LOGPROB_THRESHOLD = {best['tau']:.2f}")
    print(f"  TPR (correctly accepted)   = {best['tpr']:.4f}")
    print(f"  FPR (incorrectly accepted) = {best['fpr']:.4f}")
    print(f"  Youden's J                 = {best['j']:.4f}")
    print(f"  Sample size                = {n_total}")
    print()
    print("Paste this output back; once the per-model J check looks")
    print("symmetric I'll update router/cascade_router.py:DEFAULT_LOGPROB_THRESHOLD")
    print("and remove the TODO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
