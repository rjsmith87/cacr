"""Replay frontier_run.log into BigQuery using its original run_ts.

The first benchmark attempt (started 2026-04-28T03:06:05Z) hung mid-run
on a Gemini Pro confidence probe — see FINDINGS.md. The JSONL log
captured every completed call + summary; nothing reached BigQuery
because runner.run() returns rows and write_rows() runs only after all
tasks finish.

This script parses the log, extracts the original start timestamp from
the header line, and replays everything via write_rows(run_ts=...).
The writer's idempotent dedup means re-running this script is safe.

After this script, scripts/run_pro_codesum_only.py can append the
remaining 14 Gemini Pro CodeSummarization examples under the same
run_ts and the dedup will catch the 16 already-written rows.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import _load_dotenv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_load_dotenv(os.path.join(ROOT, ".env"))

from results.bq_writer import write_rows  # noqa: E402

LOG_PATH = os.path.join(ROOT, "results", "frontier_run.log")
START_RE = re.compile(r"=== Benchmark run started (\S+) ===")


def parse_log(path: str) -> tuple[str, list[dict]]:
    rows: list[dict] = []
    run_ts: str | None = None
    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = START_RE.search(line)
            if m and run_ts is None:
                run_ts = m.group(1)
                continue
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") in ("call", "summary"):
                rows.append(rec)
    if run_ts is None:
        raise RuntimeError(f"Could not find start timestamp in {path}")
    return run_ts, rows


def main() -> int:
    project = os.environ.get("GCP_PROJECT")
    if not project:
        print("ERROR: GCP_PROJECT not set.", file=sys.stderr)
        return 1

    run_ts, rows = parse_log(LOG_PATH)
    n_calls = sum(1 for r in rows if r["event"] == "call")
    n_summaries = sum(1 for r in rows if r["event"] == "summary")
    print(f"Parsed {LOG_PATH}")
    print(f"  run_ts:      {run_ts}")
    print(f"  call rows:   {n_calls}")
    print(f"  summary rows:{n_summaries}")
    print()

    print(f"Writing to BigQuery (project={project}) with idempotent dedup...")
    written = write_rows(rows, project=project, run_ts=run_ts)
    print(f"  {written} new rows written (existing rows under this run_ts skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
