"""CVE detection pipeline — 2-step chain.

Step 1: Detect vulnerability (yes/no + severity + confidence 1-10)
Step 2: Explain attack vector and fix (only runs if step 1 says vulnerable)

Runs 3 routing strategies across all 6 CVEs with all 4 models on step 1.
Writes results to BigQuery pipeline_results table.
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any

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
from tasks.cve_detection import ALL_CVES  # noqa: E402

# ── Prompts ────────────────────────────────────────────────────────

STEP1_PROMPT = """\
Analyze the following Python code for security vulnerabilities.

```python
{code}
```

Respond in EXACTLY this format (3 lines, nothing else):
vulnerable: yes or no
severity: critical, high, medium, low, or none
confidence: 1-10"""

STEP2_PROMPT = """\
The following Python code has been identified as having a {severity}-severity security vulnerability.

```python
{code}
```

Provide:
1. A one-paragraph description of the attack vector
2. A one-paragraph description of the fix

Respond in this format:
ATTACK: <description>
FIX: <description>"""


def _parse_step1(output: str) -> dict[str, Any]:
    """Parse step 1 output into structured fields."""
    result = {"is_vulnerable": None, "severity": None, "confidence": None}
    for line in output.lower().splitlines():
        line = line.strip()
        if line.startswith("vulnerable:"):
            val = line.split(":", 1)[1].strip()
            result["is_vulnerable"] = "yes" in val
        elif line.startswith("severity:"):
            val = line.split(":", 1)[1].strip().rstrip(".,")
            for sev in ("critical", "high", "medium", "low", "none"):
                if sev in val:
                    result["severity"] = sev
                    break
        elif line.startswith("confidence:"):
            m = re.search(r"(\d+)", line)
            if m:
                result["confidence"] = int(m.group(1))
    return result


def _parse_step2(output: str) -> dict[str, str]:
    """Parse step 2 output into attack/fix descriptions."""
    result = {"attack_description": "", "fix_description": ""}
    lines = output.strip().split("\n")
    for line in lines:
        if line.upper().startswith("ATTACK:"):
            result["attack_description"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("FIX:"):
            result["fix_description"] = line.split(":", 1)[1].strip()
    # If structured parsing fails, take first half as attack, second as fix
    if not result["attack_description"] and len(lines) >= 2:
        mid = len(lines) // 2
        result["attack_description"] = " ".join(lines[:mid])
        result["fix_description"] = " ".join(lines[mid:])
    return result


# ── Routing strategies ─────────────────────────────────────────────
# always_tier1: cheapest tier-1 model (Flash Lite)
# always_tier2: tier-2 model (GPT-4o-mini)
# cacr: step 1 uses Flash Lite (cheapest passing), step 2 uses Haiku (best score)

STRATEGIES = {
    "always_tier1": {"step1": "flash-lite", "step2": "flash-lite"},
    "always_tier2": {"step1": "gpt4o-mini", "step2": "gpt4o-mini"},
    "cacr": {"step1": "flash-lite", "step2": "haiku"},
}


def _init_models() -> dict[str, Model]:
    models: dict[str, Model] = {}
    for name, cls in [("haiku", ClaudeHaiku), ("flash", GeminiFlash),
                      ("flash-lite", GeminiFlashLite), ("gpt4o-mini", GPT4oMini)]:
        try:
            models[name] = cls()
        except Exception as exc:
            print(f"  WARN: could not init {name}: {exc}", file=sys.stderr)
    return models


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class CVEResult:
    event: str
    strategy: str
    cve_id: str
    gold_severity: str
    step1_model: str
    step1_detected: bool | None
    step1_severity: str | None
    step1_confidence: int | None
    step1_correct: bool
    step1_latency_ms: float
    step2_model: str | None
    step2_attack: str
    step2_fix: str
    step2_latency_ms: float
    total_cost_usd: float
    missed_high_severity: bool  # key metric: missed a high/critical CVE
    overconfident_miss: bool    # missed + confidence >= 8


def _emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)


def run_cve_pipeline(
    cves: list[dict[str, Any]],
    strategy_name: str,
    model_map: dict[str, str],
    models: dict[str, Model],
    all_model_step1: bool = False,
) -> list[dict[str, Any]]:
    """Run CVE pipeline. If all_model_step1=True, run step 1 with every model."""
    results = []

    step1_models_to_run = list(models.items()) if all_model_step1 else [(model_map["step1"], models[model_map["step1"]])]

    for cve in cves:
        cve_id = cve["cve_id"]
        code = cve["code"]
        gold_sev = cve["severity"]
        gold_vuln = cve["is_vulnerable"]

        for m1_name, m1 in step1_models_to_run:
            total_cost = 0.0

            # Step 1: detect vulnerability
            p1 = STEP1_PROMPT.format(code=code)
            t0 = time.perf_counter()
            try:
                out1 = m1.generate(p1)
            except Exception as e:
                out1 = f"ERROR: {e}"
            lat1 = (time.perf_counter() - t0) * 1000
            total_cost += _est_tokens(p1 + out1) * m1.cost_per_token

            parsed1 = _parse_step1(out1)
            detected = parsed1["is_vulnerable"]
            sev = parsed1["severity"]
            conf = parsed1["confidence"]

            # Correctness: did it correctly detect the vulnerability?
            s1_correct = (detected == gold_vuln)
            if s1_correct and detected and sev:
                # Also check severity is close enough
                sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}
                s1_correct = abs(sev_order.get(sev, 0) - sev_order.get(gold_sev, 0)) <= 1

            # Step 2: only runs if step 1 says vulnerable
            s2_model = None
            s2_attack = ""
            s2_fix = ""
            lat2 = 0.0
            if detected:
                m2_name = model_map["step2"]
                m2 = models.get(m2_name, m1)  # fallback to same model
                s2_model = m2_name
                p2 = STEP2_PROMPT.format(code=code, severity=sev or "unknown")
                t0 = time.perf_counter()
                try:
                    out2 = m2.generate(p2)
                except Exception as e:
                    out2 = f"ERROR: {e}"
                lat2 = (time.perf_counter() - t0) * 1000
                total_cost += _est_tokens(p2 + out2) * m2.cost_per_token
                parsed2 = _parse_step2(out2)
                s2_attack = parsed2["attack_description"][:300]
                s2_fix = parsed2["fix_description"][:300]

            # Key metrics
            missed_high = (not detected) and gold_vuln and gold_sev in ("critical", "high")
            overconfident_miss = missed_high and conf is not None and conf >= 8

            row = asdict(CVEResult(
                event="cve_call",
                strategy=strategy_name,
                cve_id=cve_id,
                gold_severity=gold_sev,
                step1_model=m1_name,
                step1_detected=detected,
                step1_severity=sev,
                step1_confidence=conf,
                step1_correct=s1_correct,
                step1_latency_ms=round(lat1, 2),
                step2_model=s2_model,
                step2_attack=s2_attack,
                step2_fix=s2_fix,
                step2_latency_ms=round(lat2, 2),
                total_cost_usd=total_cost,
                missed_high_severity=missed_high,
                overconfident_miss=overconfident_miss,
            ))
            _emit(row)
            results.append(row)

    return results


def main() -> int:
    models = _init_models()
    if not models:
        print("FATAL: no models available", file=sys.stderr)
        return 1

    all_results: list[dict[str, Any]] = []

    # Run each strategy
    for strat_name, model_map in STRATEGIES.items():
        needed = set(model_map.values())
        if not needed.issubset(models.keys()):
            missing = needed - models.keys()
            _emit({"event": "skip_strategy", "strategy": strat_name, "missing": list(missing)})
            continue
        results = run_cve_pipeline(ALL_CVES, strat_name, model_map, models)
        all_results.extend(results)

    # Also run step 1 with ALL models to compare detection rates
    all_model_results = run_cve_pipeline(
        ALL_CVES, "all_models_step1",
        {"step1": "haiku", "step2": "haiku"},  # step2 doesn't matter here
        models,
        all_model_step1=True,
    )
    all_results.extend(all_model_results)

    # Summaries
    print("\n=== CVE Detection Summary ===", file=sys.stderr)
    by_model: dict[str, list[dict]] = {}
    for r in all_results:
        if r["event"] == "cve_call":
            by_model.setdefault(r["step1_model"], []).append(r)

    for model, rows in sorted(by_model.items()):
        detected = sum(1 for r in rows if r["step1_detected"])
        correct = sum(1 for r in rows if r["step1_correct"])
        missed_high = sum(1 for r in rows if r["missed_high_severity"])
        overconf = sum(1 for r in rows if r["overconfident_miss"])
        confs = [r["step1_confidence"] for r in rows if r["step1_confidence"] is not None]
        mean_conf = sum(confs) / len(confs) if confs else 0

        summary = {
            "event": "cve_summary",
            "model": model,
            "n": len(rows),
            "detected": detected,
            "detection_rate": round(detected / len(rows), 3) if rows else 0,
            "correct": correct,
            "accuracy": round(correct / len(rows), 3) if rows else 0,
            "missed_high_severity": missed_high,
            "overconfident_misses": overconf,
            "mean_confidence": round(mean_conf, 1),
        }
        _emit(summary)
        all_results.append(summary)
        print(
            f"  {model:22s} detect={detected}/{len(rows)} correct={correct}/{len(rows)} "
            f"missed_high={missed_high} overconf_miss={overconf} conf={mean_conf:.1f}",
            file=sys.stderr,
        )

    # Write to BigQuery
    project = os.environ.get("GCP_PROJECT")
    if project:
        try:
            from results.bq_writer import _build_bq_client, _ensure_table
            from google.cloud import bigquery

            client = _build_bq_client(project)
            dataset_ref = bigquery.DatasetReference(project, "cacr_results")
            ds = bigquery.Dataset(dataset_ref)
            ds.location = "US"
            client.create_dataset(ds, exists_ok=True)

            schema = [
                bigquery.SchemaField("event", "STRING"),
                bigquery.SchemaField("strategy", "STRING"),
                bigquery.SchemaField("cve_id", "STRING"),
                bigquery.SchemaField("gold_severity", "STRING"),
                bigquery.SchemaField("step1_model", "STRING"),
                bigquery.SchemaField("step1_detected", "BOOLEAN"),
                bigquery.SchemaField("step1_severity", "STRING"),
                bigquery.SchemaField("step1_confidence", "INTEGER"),
                bigquery.SchemaField("step1_correct", "BOOLEAN"),
                bigquery.SchemaField("step1_latency_ms", "FLOAT"),
                bigquery.SchemaField("step2_model", "STRING"),
                bigquery.SchemaField("step2_attack", "STRING"),
                bigquery.SchemaField("step2_fix", "STRING"),
                bigquery.SchemaField("step2_latency_ms", "FLOAT"),
                bigquery.SchemaField("total_cost_usd", "FLOAT"),
                bigquery.SchemaField("missed_high_severity", "BOOLEAN"),
                bigquery.SchemaField("overconfident_miss", "BOOLEAN"),
                bigquery.SchemaField("model", "STRING"),
                bigquery.SchemaField("n", "INTEGER"),
                bigquery.SchemaField("detected", "INTEGER"),
                bigquery.SchemaField("detection_rate", "FLOAT"),
                bigquery.SchemaField("correct", "INTEGER"),
                bigquery.SchemaField("accuracy", "FLOAT"),
                bigquery.SchemaField("overconfident_misses", "INTEGER"),
                bigquery.SchemaField("mean_confidence", "FLOAT"),
            ]
            table = _ensure_table(client, dataset_ref, "cve_results", schema)
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
