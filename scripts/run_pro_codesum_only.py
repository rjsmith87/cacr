"""Re-run Gemini 2.5 Pro on CodeSummarization only, append to BQ.

The first frontier run hung after writing 16 of 30 Pro CodeSummarization
calls. scripts/replay_log_to_bq.py replayed those 16 to BigQuery under
run_ts=2026-04-28T03:06:05.937924+00:00. This script runs the full 30
examples for Pro/CodeSummarization with the timeout fix in place, and
writes under the SAME run_ts — the BQ writer's idempotent dedup catches
the 16 already there, so only the missing 14 get appended.

The Gemini Pro adapter now has HttpOptions(timeout=60_000) and treats
httpx.TimeoutException/NetworkError as retryable, so a stuck socket
will surface as a retry then an error rather than an indefinite hang.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import _load_dotenv, run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_load_dotenv(os.path.join(ROOT, ".env"))

from results.bq_writer import write_rows  # noqa: E402
from router.cost_model import MODEL_COSTS  # noqa: E402
from scripts.run_new_models import InstrumentedGeminiPro  # noqa: E402
from tasks.code_summarization import CodeSummarization  # noqa: E402

ORIGINAL_RUN_TS = "2026-04-28T03:06:05.937924+00:00"


def main() -> int:
    project = os.environ.get("GCP_PROJECT")
    if not project:
        print("ERROR: GCP_PROJECT not set.", file=sys.stderr)
        return 1

    tasks = [CodeSummarization()]
    models = [InstrumentedGeminiPro()]

    started = datetime.now(timezone.utc)
    print(f"=== Pro x CodeSummarization re-run started {started.isoformat()} ===", flush=True)
    print(f"  appending under original run_ts: {ORIGINAL_RUN_TS}", flush=True)
    print(f"  expected new rows: 30 calls + 1 summary - 16 existing calls = 15", flush=True)
    print()

    rows = run(tasks, models)

    finished = datetime.now(timezone.utc)
    elapsed_s = (finished - started).total_seconds()
    print(f"\n=== Re-run finished in {elapsed_s:.0f}s ===", flush=True)

    m = models[0]
    rates = MODEL_COSTS[m.name]
    cost = m.total_input * rates["input"] + (m.total_output + m.total_reasoning) * rates["output"]
    print(f"  calls={m.n_calls} errors={m.n_errors} "
          f"in={m.total_input} out={m.total_output} reasoning={m.total_reasoning} "
          f"cost=${cost:.4f}")

    print("\n=== Writing to BigQuery (idempotent dedup) ===")
    written = write_rows(rows, project=project, run_ts=ORIGINAL_RUN_TS)
    print(f"  {written} new rows written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
