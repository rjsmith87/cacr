"""Scale study: gemini-2.5-flash on the 12-CVE battery, n=30 per CVE.

Background
    The "Flash silently misses 6/12 CVEs" claim in the v1 docs has been
    retracted (commit 6b31a13) — it was 503 timeouts, not capability.
    Live n=1 sweep on 2026-04-28 shows Flash detects all 12 correctly
    with confidence 8-10. This study answers the open question: do
    silent failures surface under sustained load, where the original
    503s came from?

What it does
    For each of the 12 CVEs in the battery, runs `gemini-2.5-flash`
    against the standard step-1 detection prompt 30 times. Records:

      - raw output (full text)
      - parsed (is_vulnerable, severity, confidence)
      - whether parsing succeeded (all 3 fields parsed, non-null)
      - latency_ms
      - retry_count and per-retry error metadata
      - final_status: "success" / "exhausted"

    Pacing is 1.5 seconds between calls — slow enough to avoid being
    banned, fast enough to actually exercise sustained load (which
    is the regime where 503s historically surfaced). The adapter's
    default 6s pacing is intentionally bypassed here because the
    whole point is to push the rate up.

Output
    results/cve_scale_study.jsonl  — one JSON object per call,
                                      written incrementally
    BigQuery cacr_results.cve_scale_study  — same data, written
                                              after the run finishes

Usage
    set -a && . ./.env && set +a
    python scripts/cve_scale_study.py [--attempts N] [--cves M]

    --attempts N: per-CVE attempt count (default 30)
    --cves M    : limit to first M CVEs (default 12, all)
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from runner import _load_dotenv  # noqa: E402

_load_dotenv(os.path.join(_ROOT, ".env"))

import httpx  # noqa: E402
from google import genai  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402

from tasks.cve_detection import ALL_CVES  # noqa: E402

# ── Config ───────────────────────────────────────────────────────────
PROMPT = """\
Analyze the following Python code for security vulnerabilities.

```python
{code}
```

Respond in EXACTLY this format (3 lines, nothing else):
vulnerable: yes or no
severity: critical, high, medium, low, or none
confidence: 1-10"""

MIN_INTERVAL_S = 1.5  # pacing between requests; deliberately faster
                     # than the adapter's 6s default to push the rate
MAX_RETRIES = 5      # per-attempt retry budget
BASE_DELAY_S = 4.0   # exponential backoff base on 429/503/timeouts

OUT_PATH = os.path.join(_ROOT, "results", "cve_scale_study.jsonl")
BQ_TABLE = "cve_scale_study"
BQ_DATASET = "cacr_results"


# ── Parser ───────────────────────────────────────────────────────────
def parse_step1(out: str) -> dict:
    """Return {is_vulnerable, severity, confidence}, all None if missing."""
    result = {"is_vulnerable": None, "severity": None, "confidence": None}
    for line in (out or "").lower().splitlines():
        line = line.strip()
        if line.startswith("vulnerable:"):
            result["is_vulnerable"] = "yes" in line
        elif line.startswith("severity:"):
            for s in ("critical", "high", "medium", "low", "none"):
                if s in line:
                    result["severity"] = s
                    break
        elif line.startswith("confidence:"):
            m = re.search(r"\d+", line)
            if m:
                result["confidence"] = int(m.group(0))
    return result


# ── BQ schema ────────────────────────────────────────────────────────
def _bq_schema():
    from google.cloud import bigquery
    return [
        bigquery.SchemaField("run_ts", "TIMESTAMP"),
        bigquery.SchemaField("cve_id", "STRING"),
        bigquery.SchemaField("attempt", "INTEGER"),
        bigquery.SchemaField("gold_severity", "STRING"),
        bigquery.SchemaField("gold_is_vulnerable", "BOOL"),
        bigquery.SchemaField("raw_output", "STRING"),
        bigquery.SchemaField("output_length", "INTEGER"),
        bigquery.SchemaField("parsed_is_vulnerable", "BOOL"),
        bigquery.SchemaField("parsed_severity", "STRING"),
        bigquery.SchemaField("parsed_confidence", "INTEGER"),
        bigquery.SchemaField("parse_succeeded", "BOOL"),
        bigquery.SchemaField("detection_correct", "BOOL"),
        bigquery.SchemaField("latency_ms", "FLOAT"),
        bigquery.SchemaField("retry_count", "INTEGER"),
        bigquery.SchemaField("final_status", "STRING"),
        bigquery.SchemaField("errors", "JSON"),
    ]


def _ensure_bq_table(client, project: str):
    from google.cloud import bigquery
    dataset_ref = bigquery.DatasetReference(project, BQ_DATASET)
    table_ref = dataset_ref.table(BQ_TABLE)
    table = bigquery.Table(table_ref, schema=_bq_schema())
    return client.create_table(table, exists_ok=True)


# ── Single-attempt runner ────────────────────────────────────────────
def run_attempt(genai_client, model_id, config, prompt) -> dict:
    """Run one Flash request with retry + error capture. Returns a dict
    suitable for both JSONL and BQ rows.
    """
    retries = 0
    errors: list[dict] = []
    output = ""
    final_status = "success"
    final_latency_ms = 0.0

    for try_num in range(MAX_RETRIES):
        t0 = time.perf_counter()
        try:
            resp = genai_client.models.generate_content(
                model=model_id, contents=prompt, config=config,
            )
            final_latency_ms = (time.perf_counter() - t0) * 1000
            output = (resp.text or "").strip()
            break
        except (genai_errors.ServerError, genai_errors.ClientError) as exc:
            final_latency_ms = (time.perf_counter() - t0) * 1000
            code = getattr(exc, "status_code", 0) or 0
            errors.append({
                "try_num": try_num,
                "type": type(exc).__name__,
                "code": code,
                "msg": str(exc)[:300],
            })
            if try_num < MAX_RETRIES - 1 and code in (429, 503):
                retries += 1
                time.sleep(BASE_DELAY_S * (2 ** try_num))
                continue
            final_status = "exhausted"
            break
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            final_latency_ms = (time.perf_counter() - t0) * 1000
            errors.append({
                "try_num": try_num,
                "type": type(exc).__name__,
                "code": 0,
                "msg": str(exc)[:300],
            })
            if try_num < MAX_RETRIES - 1:
                retries += 1
                time.sleep(BASE_DELAY_S * (2 ** try_num))
                continue
            final_status = "exhausted"
            break

    return {
        "raw_output": output,
        "output_length": len(output),
        "latency_ms": round(final_latency_ms, 2),
        "retry_count": retries,
        "errors": errors,
        "final_status": final_status,
    }


# ── Main ─────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--cves", type=int, default=len(ALL_CVES))
    args = parser.parse_args(argv[1:])

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not in environment.", file=sys.stderr)
        return 1
    project = os.environ.get("GCP_PROJECT")

    cves = ALL_CVES[: args.cves]
    total = len(cves) * args.attempts
    print(f"Scale study: {len(cves)} CVEs × {args.attempts} attempts = {total} calls")
    print(f"Pacing: {MIN_INTERVAL_S}s between requests, {MAX_RETRIES} retries on 429/503/timeout")
    print(f"Output: {OUT_PATH}")
    print(f"BQ:     {project}:{BQ_DATASET}.{BQ_TABLE}" if project else "BQ:     skipped (no GCP_PROJECT)")
    print()

    genai_client = genai.Client(api_key=api_key)
    model_id = "gemini-2.5-flash"
    config = genai.types.GenerateContentConfig(
        max_output_tokens=1024,
        temperature=0.0,
        thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
    )

    run_ts = datetime.now(timezone.utc).isoformat()
    started = time.time()
    last_call_ts = 0.0
    rows: list[dict] = []

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        for cve_idx, cve in enumerate(cves):
            for attempt in range(1, args.attempts + 1):
                # Pacing
                elapsed = time.time() - last_call_ts
                if elapsed < MIN_INTERVAL_S:
                    time.sleep(MIN_INTERVAL_S - elapsed)
                last_call_ts = time.time()

                prompt = PROMPT.format(code=cve["code"])
                attempt_data = run_attempt(genai_client, model_id, config, prompt)
                parsed = parse_step1(attempt_data["raw_output"])
                parse_succeeded = all(v is not None for v in parsed.values())
                detection_correct = (
                    parse_succeeded
                    and parsed["is_vulnerable"] == cve["is_vulnerable"]
                )

                row = {
                    "run_ts": run_ts,
                    "cve_id": cve["cve_id"],
                    "attempt": attempt,
                    "gold_severity": cve["severity"],
                    "gold_is_vulnerable": cve["is_vulnerable"],
                    "raw_output": attempt_data["raw_output"],
                    "output_length": attempt_data["output_length"],
                    "parsed_is_vulnerable": parsed["is_vulnerable"],
                    "parsed_severity": parsed["severity"],
                    "parsed_confidence": parsed["confidence"],
                    "parse_succeeded": parse_succeeded,
                    "detection_correct": detection_correct,
                    "latency_ms": attempt_data["latency_ms"],
                    "retry_count": attempt_data["retry_count"],
                    "final_status": attempt_data["final_status"],
                    "errors": attempt_data["errors"],
                }
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                rows.append(row)

                # Progress every 30 calls (= per CVE) or on errors
                done = cve_idx * args.attempts + attempt
                if attempt == args.attempts or attempt_data["retry_count"] > 0 or attempt_data["final_status"] != "success":
                    elapsed_min = (time.time() - started) / 60
                    marker = ""
                    if attempt_data["final_status"] != "success":
                        marker = f" [{attempt_data['final_status']}]"
                    if attempt_data["retry_count"] > 0:
                        marker += f" [retries={attempt_data['retry_count']}]"
                    if not parse_succeeded:
                        marker += " [parse_failed]"
                    elif not detection_correct:
                        marker += " [wrong]"
                    print(
                        f"  [{done:>3d}/{total}, {elapsed_min:.1f}min] "
                        f"{cve['cve_id']:18s} attempt {attempt:2d}/{args.attempts} "
                        f"latency={attempt_data['latency_ms']:.0f}ms{marker}",
                        flush=True,
                    )

    elapsed_total = time.time() - started
    print(f"\nFinished in {elapsed_total/60:.1f} min ({elapsed_total:.0f}s)")
    print(f"  rows in JSONL: {len(rows)}")

    # ── Write to BigQuery ───────────────────────────────────────────
    if project:
        try:
            from google.cloud import bigquery
            from results.bq_writer import _build_bq_client
            client = _build_bq_client(project)
            table = _ensure_bq_table(client, project)
            # JSON column needs str-encoded values
            bq_rows = []
            for r in rows:
                br = dict(r)
                br["errors"] = json.dumps(r["errors"]) if r["errors"] else None
                bq_rows.append(br)
            errs = client.insert_rows_json(table, bq_rows)
            if errs:
                print(f"  BQ insert errors: {errs[:3]}")
            else:
                print(f"  wrote {len(bq_rows)} rows to {project}:{BQ_DATASET}.{BQ_TABLE}")
        except Exception as exc:
            print(f"  BQ write FAILED: {type(exc).__name__}: {exc}")

    # ── Report ──────────────────────────────────────────────────────
    print("\n=== Per-CVE report ===")
    by_cve: dict[str, list[dict]] = {}
    for r in rows:
        by_cve.setdefault(r["cve_id"], []).append(r)
    print(f"\n{'CVE':18s}  {'gold':9s}  {'detect':>9s}  {'parse_ok':>9s}  {'errors':>7s}  {'mean_lat':>9s}  {'conf_distribution':<20s}")
    print("-" * 110)
    for cve_id in sorted(by_cve.keys()):
        attempts = by_cve[cve_id]
        n = len(attempts)
        n_correct = sum(1 for a in attempts if a["detection_correct"])
        n_parse_ok = sum(1 for a in attempts if a["parse_succeeded"])
        n_errored = sum(1 for a in attempts if a["final_status"] != "success")
        n_retries = sum(a["retry_count"] for a in attempts)
        confs = [a["parsed_confidence"] for a in attempts if a["parsed_confidence"] is not None]
        conf_min = min(confs) if confs else None
        conf_max = max(confs) if confs else None
        conf_med = sorted(confs)[len(confs)//2] if confs else None
        latencies = [a["latency_ms"] for a in attempts]
        mean_lat = sum(latencies) / len(latencies) if latencies else 0
        gold_sev = attempts[0]["gold_severity"]
        conf_str = f"min={conf_min} med={conf_med} max={conf_max}" if confs else "no parsed"
        print(f"  {cve_id:18s}  {gold_sev:9s}  {n_correct}/{n:<7d}  {n_parse_ok}/{n:<7d}  {n_errored:>3d}/{n_retries:<3d}  {mean_lat:>7.0f}ms  {conf_str}")

    print()
    total_calls = len(rows)
    total_errored = sum(1 for r in rows if r["final_status"] != "success")
    total_parse_failed = sum(1 for r in rows if not r["parse_succeeded"])
    total_correct = sum(1 for r in rows if r["detection_correct"])
    total_retries = sum(r["retry_count"] for r in rows)
    error_codes = {}
    for r in rows:
        for e in r["errors"]:
            c = e.get("code", 0)
            error_codes[c] = error_codes.get(c, 0) + 1
    all_confs = [r["parsed_confidence"] for r in rows if r["parsed_confidence"] is not None]

    print(f"=== Overall ({total_calls} calls) ===")
    print(f"  detection_correct: {total_correct}/{total_calls} ({100*total_correct/total_calls:.1f}%)")
    print(f"  parse_succeeded:   {total_calls - total_parse_failed}/{total_calls} ({100*(total_calls - total_parse_failed)/total_calls:.1f}%)")
    print(f"  parse_failed:      {total_parse_failed}/{total_calls} ({100*total_parse_failed/total_calls:.1f}%)  ← silent failures")
    print(f"  final_status != success: {total_errored}/{total_calls} ({100*total_errored/total_calls:.1f}%)")
    print(f"  total retries: {total_retries}")
    if error_codes:
        print(f"  error codes encountered: {sorted(error_codes.items())}")
    else:
        print(f"  error codes encountered: none")
    if all_confs:
        from collections import Counter
        bins = Counter(all_confs)
        bin_str = " ".join(f"{k}:{v}" for k, v in sorted(bins.items()))
        print(f"  confidence histogram (parsed only, n={len(all_confs)}): {bin_str}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
