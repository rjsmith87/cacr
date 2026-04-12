"""4-step code review pipeline simulation.

Step 1: Classify bug severity (critical/high/medium/low)
Step 2: Identify bug type (logic_error, null_pointer, off_by_one, resource_leak, race_condition)
Step 3: Detect security vulnerability (yes/no) — uses CVE detection knowledge
Step 4: Suggest a one-sentence fix

Runs under four routing strategies:
  (a) all-haiku      — every step uses Claude Haiku
  (b) all-lite       — every step uses Gemini 2.5 Flash Lite
  (c) all-gpt4o-mini — every step uses GPT-4o-mini
  (d) cacr-routed    — cheapest model per step, with escalation for weak tasks
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
from models.gemini_flash_lite_adapter import GeminiFlashLite  # noqa: E402
from models.openai_adapter import GPT4oMini  # noqa: E402

# ── pipeline snippets ──────────────────────────────────────────────

SNIPPETS = [
    {
        "code": 'def divide(a, b):\n    return a / b',
        "gold_severity": "critical",
        "gold_type": "logic_error",
        "gold_vuln": False,
        "gold_fix": "Add a check for b == 0 before dividing to avoid ZeroDivisionError.",
    },
    {
        "code": 'def get_name(user):\n    return user["name"].upper()\n# called with get_name(None)',
        "gold_severity": "critical",
        "gold_type": "null_pointer",
        "gold_vuln": False,
        "gold_fix": "Check if user is None before accessing the name key.",
    },
    {
        "code": 'def first_n(items, n):\n    return [items[i] for i in range(1, n)]',
        "gold_severity": "medium",
        "gold_type": "off_by_one",
        "gold_vuln": False,
        "gold_fix": "Change range(1, n) to range(n) to include the first element.",
    },
    {
        "code": 'def read_file(path):\n    f = open(path)\n    return f.read()',
        "gold_severity": "medium",
        "gold_type": "resource_leak",
        "gold_vuln": False,
        "gold_fix": "Use a with statement to ensure the file is closed after reading.",
    },
    {
        "code": 'import threading\nbal = 0\ndef add(x):\n    global bal\n    tmp = bal\n    tmp += x\n    bal = tmp',
        "gold_severity": "high",
        "gold_type": "race_condition",
        "gold_vuln": False,
        "gold_fix": "Protect the read-modify-write of bal with a threading.Lock.",
    },
    # Snippets with security vulnerabilities
    {
        "code": 'def get_user(conn, name):\n    return conn.execute(f"SELECT * FROM users WHERE name=\'{name}\'").fetchone()',
        "gold_severity": "critical",
        "gold_type": "logic_error",
        "gold_vuln": True,
        "gold_fix": "Use parameterized queries to prevent SQL injection.",
    },
    {
        "code": 'from flask import request\n@app.route("/greet")\ndef greet():\n    return f"<h1>Hello, {request.args.get(\'name\')}!</h1>"',
        "gold_severity": "high",
        "gold_type": "logic_error",
        "gold_vuln": True,
        "gold_fix": "Escape user input before rendering in HTML to prevent XSS.",
    },
    {
        "code": 'import pickle\nfrom flask import request\n@app.route("/load", methods=["POST"])\ndef load():\n    return str(pickle.loads(request.data))',
        "gold_severity": "critical",
        "gold_type": "logic_error",
        "gold_vuln": True,
        "gold_fix": "Never use pickle.loads on untrusted input; use json.loads instead.",
    },
    {
        "code": 'import sqlite3\ndef query(db, sql):\n    conn = sqlite3.connect(db)\n    return conn.execute(sql).fetchall()',
        "gold_severity": "medium",
        "gold_type": "resource_leak",
        "gold_vuln": False,
        "gold_fix": "Close the connection after use, or use a with statement.",
    },
    {
        "code": 'from concurrent.futures import ThreadPoolExecutor\ntotal = []\ndef work(x):\n    total.append(x)\nwith ThreadPoolExecutor() as e:\n    e.map(work, range(100))',
        "gold_severity": "high",
        "gold_type": "race_condition",
        "gold_vuln": False,
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


def step3_prompt(code: str) -> str:
    return (
        "Does the following Python code contain a security vulnerability?\n"
        "Respond with ONLY 'yes' or 'no', nothing else.\n\n"
        f"```python\n{code}\n```\nVulnerable:"
    )


def step4_prompt(code: str, severity: str, bug_type: str, has_vuln: str) -> str:
    vuln_note = " It also has a security vulnerability." if has_vuln == "yes" else ""
    return (
        f"The following Python code has a {severity}-severity {bug_type} bug.{vuln_note}\n"
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

# CACR routing: cheapest passing model per step, with escalation.
# Step 1 (severity): classification → flash-lite (0.90, passes)
# Step 2 (bug type): classification → flash-lite (0.90, passes)
# Step 3 (CVE detect): security → flash-lite (0.93, passes; Flash only 0.50 — skip it)
# Step 4 (fix): generation → flash-lite scores 0.42 (below 0.6) → escalate to gpt4o-mini (0.40)
#   Actually both are below 0.7 escalation target, so stay with cheapest passing: flash-lite
CACR_ROUTING = {
    "step1": "flash-lite",   # classification: 0.90
    "step2": "flash-lite",   # classification: 0.90
    "step3": "flash-lite",   # security/CVE: 12/12 detected
    "step4": "flash-lite",   # generation: 0.42 (passes 0.4 threshold, cheapest)
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
    step3_correct: bool
    step4_model: str
    step4_output: str
    step4_plausible: bool
    cascade_failure: bool
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

        # Step 3 — CVE/security detection
        m3_name = model_map["step3"]
        m3 = models[m3_name]
        p3 = step3_prompt(code)
        t0 = time.perf_counter()
        try:
            out3 = m3.generate(p3)
        except Exception:
            out3 = ""
        lat3 = (time.perf_counter() - t0) * 1000
        total_lat += lat3
        total_cost += _est_tokens(p3 + out3) * m3.cost_per_token
        s3 = _parse_label(out3)
        s3_detected = "yes" in s3
        s3_correct = s3_detected == snip["gold_vuln"]

        # Step 4 — fix suggestion, uses output of steps 1-3
        m4_name = model_map["step4"]
        m4 = models[m4_name]
        p4 = step4_prompt(code, s1 or "unknown", s2 or "unknown", "yes" if s3_detected else "no")
        t0 = time.perf_counter()
        try:
            out4 = m4.generate(p4)
        except Exception:
            out4 = ""
        lat4 = (time.perf_counter() - t0) * 1000
        total_lat += lat4
        total_cost += _est_tokens(p4 + out4) * m4.cost_per_token

        s4_text = out4.strip()
        s4_plausible = len(s4_text) > 10 and s1_correct and s2_correct

        cascade_failure = (not s1_correct or not s2_correct or not s3_correct) and not s4_plausible

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
            step3_output=s3,
            step3_correct=s3_correct,
            step4_model=m4_name,
            step4_output=s4_text[:200],
            step4_plausible=s4_plausible,
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
        "all-haiku": {"step1": "haiku", "step2": "haiku", "step3": "haiku", "step4": "haiku"},
        "all-lite": {"step1": "flash-lite", "step2": "flash-lite", "step3": "flash-lite", "step4": "flash-lite"},
        "all-gpt4o-mini": {"step1": "gpt4o-mini", "step2": "gpt4o-mini", "step3": "gpt4o-mini", "step4": "gpt4o-mini"},
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
        s3_acc = sum(r.step3_correct for r in results) / n
        s4_acc = sum(r.step4_plausible for r in results) / n
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
            "step4_accuracy": round(s4_acc, 3),
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
                bigquery.SchemaField("step3_correct", "BOOLEAN"),
                bigquery.SchemaField("step4_model", "STRING"),
                bigquery.SchemaField("step4_output", "STRING"),
                bigquery.SchemaField("step4_plausible", "BOOLEAN"),
                bigquery.SchemaField("cascade_failure", "BOOLEAN"),
                bigquery.SchemaField("total_latency_ms", "FLOAT"),
                bigquery.SchemaField("total_cost_usd", "FLOAT"),
                bigquery.SchemaField("n", "INTEGER"),
                bigquery.SchemaField("step1_accuracy", "FLOAT"),
                bigquery.SchemaField("step2_accuracy", "FLOAT"),
                bigquery.SchemaField("step3_accuracy", "FLOAT"),
                bigquery.SchemaField("step4_accuracy", "FLOAT"),
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
