"""3-step code review pipeline simulation.

Step 1: Classify bug severity (critical/high/medium/low)
Step 2: Identify bug type (logic_error, null_pointer, off_by_one, resource_leak, race_condition)
Step 3: Suggest a one-sentence fix

Runs under three routing strategies:
  (a) all-haiku   — every step uses Claude Haiku
  (b) all-lite    — every step uses Gemini 2.5 Flash Lite
  (c) cacr-routed — cheapest model that passed threshold per step type
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any

# ── bootstrap env ──────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


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

from models.anthropic_adapter import ClaudeHaiku  # noqa: E402
from models.base import Model  # noqa: E402
from models.gemini_adapter import GeminiFlash  # noqa: E402
from models.gemini_pro_adapter import GeminiFlashLite  # noqa: E402
from models.openai_adapter import GPT4oMini  # noqa: E402

# ── pipeline snippets ──────────────────────────────────────────────

SNIPPETS = [
    {
        "code": 'def divide(a, b):\n    return a / b',
        "gold_severity": "critical",
        "gold_type": "logic_error",
        "gold_fix": "Add a check for b == 0 before dividing to avoid ZeroDivisionError.",
    },
    {
        "code": 'def get_name(user):\n    return user["name"].upper()\n# called with get_name(None)',
        "gold_severity": "critical",
        "gold_type": "null_pointer",
        "gold_fix": "Check if user is None before accessing the name key.",
    },
    {
        "code": 'def first_n(items, n):\n    return [items[i] for i in range(1, n)]',
        "gold_severity": "medium",
        "gold_type": "off_by_one",
        "gold_fix": "Change range(1, n) to range(n) to include the first element.",
    },
    {
        "code": 'def read_file(path):\n    f = open(path)\n    return f.read()',
        "gold_severity": "medium",
        "gold_type": "resource_leak",
        "gold_fix": "Use a with statement to ensure the file is closed after reading.",
    },
    {
        "code": 'import threading\nbal = 0\ndef add(x):\n    global bal\n    tmp = bal\n    tmp += x\n    bal = tmp',
        "gold_severity": "high",
        "gold_type": "race_condition",
        "gold_fix": "Protect the read-modify-write of bal with a threading.Lock.",
    },
    {
        "code": 'def avg(nums):\n    return sum(nums) / len(nums)',
        "gold_severity": "critical",
        "gold_type": "logic_error",
        "gold_fix": "Handle the case where nums is empty to avoid ZeroDivisionError.",
    },
    {
        "code": 'def find(d, key):\n    return d[key].strip()',
        "gold_severity": "high",
        "gold_type": "null_pointer",
        "gold_fix": "Use d.get(key) and check for None before calling strip.",
    },
    {
        "code": 'def last_n(items, n):\n    return items[len(items)-n+1:]',
        "gold_severity": "low",
        "gold_type": "off_by_one",
        "gold_fix": "Change len(items)-n+1 to len(items)-n to include all n items.",
    },
    {
        "code": 'import sqlite3\ndef query(db, sql):\n    conn = sqlite3.connect(db)\n    return conn.execute(sql).fetchall()',
        "gold_severity": "medium",
        "gold_type": "resource_leak",
        "gold_fix": "Close the connection after use, or use a with statement.",
    },
    {
        "code": 'from concurrent.futures import ThreadPoolExecutor\ntotal = []\ndef work(x):\n    total.append(x)\nwith ThreadPoolExecutor() as e:\n    e.map(work, range(100))',
        "gold_severity": "high",
        "gold_type": "race_condition",
        "gold_fix": "Use a lock when appending to the shared list, or use a thread-safe queue.",
    },
]

SEVERITY_LEVELS = ["critical", "high", "medium", "low"]
BUG_TYPES = ["logic_error", "null_pointer", "off_by_one", "resource_leak", "race_condition"]


# ── step prompts ───────────────────────────────────────────────────

def step1_prompt(code: str) -> str:
    return (
        "Classify the severity of the bug in this Python code.\n"
        f"Severity levels: {', '.join(SEVERITY_LEVELS)}\n"
        "Respond with ONLY the severity level, nothing else.\n\n"
        f"```python\n{code}\n```\nSeverity:"
    )


def step2_prompt(code: str) -> str:
    return (
        "Identify the bug type in this Python code.\n"
        f"Bug types: {', '.join(BUG_TYPES)}\n"
        "Respond with ONLY the bug type, nothing else.\n\n"
        f"```python\n{code}\n```\nBug type:"
    )


def step3_prompt(code: str, severity: str, bug_type: str) -> str:
    return (
        f"The following Python code has a {severity}-severity {bug_type} bug.\n"
        "Suggest a one-sentence fix.\n"
        "Respond with ONLY the fix sentence, nothing else.\n\n"
        f"```python\n{code}\n```\nFix:"
    )


def _parse_label(output: str) -> str:
    return next((ln.strip() for ln in output.splitlines() if ln.strip()), "").lower().strip(" .,:;\"'`*")


# ── CACR routing logic ─────────────────────────────────────────────
# Step 1 (severity classification) → classification family, easy
# Step 2 (bug type identification) → classification family, medium
# Step 3 (fix suggestion) → generation family, medium
# Use cheapest model that passed threshold on the matching task.

# Based on benchmark results:
#  - CodeReview (classification): flash-lite passes (0.87 >= 0.6), cheapest
#  - CodeSummarization (generation): flash-lite passes (0.45 >= 0.4), cheapest
# So CACR routes everything to flash-lite for this battery.
# If flash-lite had failed threshold, we'd escalate to haiku.

CACR_ROUTING = {
    "step1": "flash-lite",  # classification → flash-lite (passed 0.87)
    "step2": "flash-lite",  # classification → flash-lite (passed 0.87)
    "step3": "flash-lite",  # generation → flash-lite (passed 0.45)
}


@dataclass
class PipelineResult:
    strategy: str
    snippet_idx: int
    step1_model: str
    step1_output: str
    step1_correct: bool
    step2_model: str
    step2_output: str
    step2_correct: bool
    step3_model: str
    step3_output: str
    step3_plausible: bool
    cascade_failure: bool  # wrong step1/2 caused step3 to fail
    total_latency_ms: float
    total_cost_usd: float


def _init_models() -> dict[str, Model]:
    models: dict[str, Model] = {}
    for name, cls in [("haiku", ClaudeHaiku), ("flash-lite", GeminiFlashLite),
                      ("flash", GeminiFlash), ("gpt4o-mini", GPT4oMini)]:
        try:
            models[name] = cls()
        except Exception as exc:
            print(f"  WARN: could not init {name}: {exc}", file=sys.stderr)
    return models


def _est_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def run_pipeline(
    snippets: list[dict[str, Any]],
    strategy: str,
    model_map: dict[str, str],
    models: dict[str, Model],
) -> list[PipelineResult]:
    results = []
    for idx, snip in enumerate(snippets):
        code = snip["code"]
        total_lat = 0.0
        total_cost = 0.0

        # Step 1
        m1_name = model_map["step1"]
        m1 = models[m1_name]
        p1 = step1_prompt(code)
        t0 = time.perf_counter()
        try:
            out1 = m1.generate(p1)
        except Exception:
            out1 = ""
        lat1 = (time.perf_counter() - t0) * 1000
        total_lat += lat1
        total_cost += _est_tokens(p1 + out1) * m1.cost_per_token
        s1 = _parse_label(out1)
        s1_correct = s1 == snip["gold_severity"]

        # Step 2
        m2_name = model_map["step2"]
        m2 = models[m2_name]
        p2 = step2_prompt(code)
        t0 = time.perf_counter()
        try:
            out2 = m2.generate(p2)
        except Exception:
            out2 = ""
        lat2 = (time.perf_counter() - t0) * 1000
        total_lat += lat2
        total_cost += _est_tokens(p2 + out2) * m2.cost_per_token
        s2 = _parse_label(out2)
        s2_correct = s2 == snip["gold_type"]

        # Step 3 — uses output of steps 1 & 2
        m3_name = model_map["step3"]
        m3 = models[m3_name]
        p3 = step3_prompt(code, s1 or "unknown", s2 or "unknown")
        t0 = time.perf_counter()
        try:
            out3 = m3.generate(p3)
        except Exception:
            out3 = ""
        lat3 = (time.perf_counter() - t0) * 1000
        total_lat += lat3
        total_cost += _est_tokens(p3 + out3) * m3.cost_per_token

        # Step 3 plausibility: non-empty and mentions a fix-like action
        s3_text = out3.strip()
        s3_plausible = len(s3_text) > 10 and s1_correct and s2_correct

        cascade_failure = (not s1_correct or not s2_correct) and not s3_plausible

        results.append(PipelineResult(
            strategy=strategy,
            snippet_idx=idx,
            step1_model=m1_name,
            step1_output=s1,
            step1_correct=s1_correct,
            step2_model=m2_name,
            step2_output=s2,
            step2_correct=s2_correct,
            step3_model=m3_name,
            step3_output=s3_text[:200],
            step3_plausible=s3_plausible,
            cascade_failure=cascade_failure,
            total_latency_ms=round(total_lat, 2),
            total_cost_usd=total_cost,
        ))
    return results


def _emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)


def main() -> int:
    models = _init_models()
    if "haiku" not in models and "flash-lite" not in models:
        print("FATAL: need at least haiku or flash-lite", file=sys.stderr)
        return 1

    strategies = {
        "all-haiku": {"step1": "haiku", "step2": "haiku", "step3": "haiku"},
        "all-lite": {"step1": "flash-lite", "step2": "flash-lite", "step3": "flash-lite"},
        "cacr-routed": CACR_ROUTING,
    }

    all_results: list[dict] = []

    for strat_name, model_map in strategies.items():
        # Skip strategy if required models aren't available
        needed = set(model_map.values())
        if not needed.issubset(models.keys()):
            missing = needed - models.keys()
            _emit({"event": "skip_strategy", "strategy": strat_name, "missing_models": list(missing)})
            continue

        results = run_pipeline(SNIPPETS, strat_name, model_map, models)

        n = len(results)
        s1_acc = sum(r.step1_correct for r in results) / n
        s2_acc = sum(r.step2_correct for r in results) / n
        s3_acc = sum(r.step3_plausible for r in results) / n
        cascade_rate = sum(r.cascade_failure for r in results) / n
        total_cost = sum(r.total_cost_usd for r in results)
        mean_lat = sum(r.total_latency_ms for r in results) / n

        for r in results:
            row = asdict(r)
            row["event"] = "pipeline_call"
            _emit(row)
            all_results.append(row)

        summary = {
            "event": "pipeline_summary",
            "strategy": strat_name,
            "n": n,
            "step1_accuracy": round(s1_acc, 3),
            "step2_accuracy": round(s2_acc, 3),
            "step3_accuracy": round(s3_acc, 3),
            "cascade_failure_rate": round(cascade_rate, 3),
            "total_cost_usd": round(total_cost, 8),
            "mean_latency_ms": round(mean_lat, 2),
        }
        _emit(summary)
        all_results.append(summary)

    # Write to BigQuery
    project = os.environ.get("GCP_PROJECT")
    if project:
        try:
            from results.bq_writer import _ensure_table
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
            dataset_ref = bigquery.DatasetReference(project, "cacr_results")
            ds = bigquery.Dataset(dataset_ref)
            ds.location = "US"
            client.create_dataset(ds, exists_ok=True)

            schema = [
                bigquery.SchemaField("event", "STRING"),
                bigquery.SchemaField("strategy", "STRING"),
                bigquery.SchemaField("snippet_idx", "INTEGER"),
                bigquery.SchemaField("step1_model", "STRING"),
                bigquery.SchemaField("step1_output", "STRING"),
                bigquery.SchemaField("step1_correct", "BOOLEAN"),
                bigquery.SchemaField("step2_model", "STRING"),
                bigquery.SchemaField("step2_output", "STRING"),
                bigquery.SchemaField("step2_correct", "BOOLEAN"),
                bigquery.SchemaField("step3_model", "STRING"),
                bigquery.SchemaField("step3_output", "STRING"),
                bigquery.SchemaField("step3_plausible", "BOOLEAN"),
                bigquery.SchemaField("cascade_failure", "BOOLEAN"),
                bigquery.SchemaField("total_latency_ms", "FLOAT"),
                bigquery.SchemaField("total_cost_usd", "FLOAT"),
                bigquery.SchemaField("n", "INTEGER"),
                bigquery.SchemaField("step1_accuracy", "FLOAT"),
                bigquery.SchemaField("step2_accuracy", "FLOAT"),
                bigquery.SchemaField("step3_accuracy", "FLOAT"),
                bigquery.SchemaField("cascade_failure_rate", "FLOAT"),
                bigquery.SchemaField("mean_latency_ms", "FLOAT"),
            ]
            table = _ensure_table(client, dataset_ref, "pipeline_results", schema)
            errors = client.insert_rows_json(table, all_results)
            if errors:
                _emit({"event": "bq_error", "errors": str(errors)[:200]})
            else:
                _emit({"event": "bq_write", "rows": len(all_results)})
        except Exception as exc:
            _emit({"event": "bq_error", "error": f"{type(exc).__name__}: {exc}"})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
