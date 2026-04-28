"""Run the full benchmark for the four new frontier models only.

Reuses runner.run() with instrumented adapter instances that record
per-call token usage so we can report actual cost (not estimate).
Writes rows to BigQuery via the existing write_rows() path — appends
to benchmark_calls + benchmark_summaries; does not re-run the existing
4 models.

Default behavior across all four models for v1 apples-to-apples:
- Gemini Pro: thinking on (cannot disable on this model anyway)
- GPT-5: default reasoning
- o3: reasoning_effort=medium (the adapter's default)
- Opus 4.7: no temperature (deprecated)

If Gemini Pro 503s after 3 retries it raises, runner records the call
as an error, and the run continues for the remaining models/examples.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner import _load_dotenv, run  # noqa: E402

_load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from anthropic import Anthropic  # noqa: E402
from google import genai  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from openai import OpenAI  # noqa: E402

from models.claude_opus_adapter import ClaudeOpus  # noqa: E402
from models.gemini_pro_adapter import GeminiPro, _MAX_RETRIES, _BASE_DELAY  # noqa: E402
from models.gpt5_adapter import GPT5  # noqa: E402
from models.o3_adapter import O3  # noqa: E402
from models.gemini_adapter import _extract_retry_delay  # noqa: E402

from results.bq_writer import write_rows  # noqa: E402
from router.cost_model import MODEL_COSTS  # noqa: E402

from tasks.code_review import CodeReview  # noqa: E402
from tasks.code_summarization import CodeSummarization  # noqa: E402
from tasks.security_vuln import SecurityVuln  # noqa: E402

import time  # noqa: E402


class UsageMixin:
    """Adds running totals: input_tokens, output_tokens, reasoning_tokens, n_calls."""

    def _init_usage(self) -> None:
        self.total_input = 0
        self.total_output = 0
        self.total_reasoning = 0
        self.n_calls = 0
        self.n_errors = 0

    def _record(self, in_tok: int, out_tok: int, reason_tok: int = 0) -> None:
        self.total_input += in_tok
        self.total_output += out_tok
        self.total_reasoning += reason_tok
        self.n_calls += 1


class InstrumentedClaudeOpus(UsageMixin, ClaudeOpus):
    def __init__(self) -> None:
        super().__init__()
        self._init_usage()

    def generate(self, prompt: str) -> str:
        try:
            resp = self._client.messages.create(
                model=self._model_id,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            self._record(resp.usage.input_tokens, resp.usage.output_tokens, 0)
            parts = [getattr(b, "text", "") for b in resp.content]
            return "".join(parts).strip()
        except Exception:
            self.n_errors += 1
            raise


class InstrumentedGPT5(UsageMixin, GPT5):
    def __init__(self) -> None:
        super().__init__()
        self._init_usage()

    def generate(self, prompt: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model_id,
                max_completion_tokens=self._max_completion_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = resp.usage
            details = getattr(usage, "completion_tokens_details", None)
            reason_tok = getattr(details, "reasoning_tokens", 0) if details else 0
            self._record(usage.prompt_tokens, usage.completion_tokens, reason_tok)
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            self.n_errors += 1
            raise


class InstrumentedO3(UsageMixin, O3):
    def __init__(self) -> None:
        super().__init__()
        self._init_usage()

    def generate(self, prompt: str) -> str:
        try:
            text = super().generate(prompt)
            u = self.last_usage or {}
            self._record(
                u.get("input_tokens", 0),
                u.get("output_tokens", 0),
                u.get("reasoning_tokens", 0),
            )
            return text
        except Exception:
            self.n_errors += 1
            raise


class InstrumentedGeminiPro(UsageMixin, GeminiPro):
    """Gemini Pro with usage tracking + the same 3-retry policy as the base."""

    def __init__(self) -> None:
        super().__init__()
        self._init_usage()

    def generate(self, prompt: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._client.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config=self._config,
                )
                u = resp.usage_metadata
                in_tok = u.prompt_token_count or 0
                out_tok = u.candidates_token_count or 0
                reason_tok = getattr(u, "thoughts_token_count", 0) or 0
                self._record(in_tok, out_tok, reason_tok)
                return (resp.text or "").strip()
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                code = getattr(exc, "status_code", 0) or 0
                if code in (429, 503):
                    last_exc = exc
                    hint = _extract_retry_delay(exc)
                    delay = hint if hint else _BASE_DELAY * (2 ** attempt)
                    print(
                        f"  [gemini-2.5-pro] {code} attempt {attempt + 1}/{_MAX_RETRIES} — "
                        f"sleeping {delay:.1f}s",
                        file=sys.stderr, flush=True,
                    )
                    time.sleep(delay)
                    continue
                self.n_errors += 1
                raise
        self.n_errors += 1
        raise last_exc  # type: ignore[misc]


def _cost_usd(model_name: str, model: UsageMixin) -> float:
    rates = MODEL_COSTS.get(model_name)
    if not rates:
        return 0.0
    # Reasoning tokens bill at the output rate.
    output_total = model.total_output + model.total_reasoning
    return model.total_input * rates["input"] + output_total * rates["output"]


def main() -> int:
    project = os.environ.get("GCP_PROJECT")
    if not project:
        print("ERROR: GCP_PROJECT not set; aborting (we need BQ writes).", file=sys.stderr)
        return 1

    tasks = [CodeReview(), SecurityVuln(), CodeSummarization()]

    models = [
        InstrumentedClaudeOpus(),
        InstrumentedGPT5(),
        InstrumentedO3(),
        InstrumentedGeminiPro(),
    ]

    started = datetime.now(timezone.utc)
    print(f"=== Benchmark run started {started.isoformat()} ===", flush=True)
    print(f"Tasks: {[t.name for t in tasks]}", flush=True)
    print(f"Models: {[m.name for m in models]}", flush=True)
    print(
        f"Expected calls: {len(tasks)} tasks × {len(tasks[0].examples())} examples × "
        f"{len(models)} models × 2 (answer+confidence) = "
        f"{len(tasks) * len(tasks[0].examples()) * len(models) * 2}",
        flush=True,
    )
    print()

    rows = run(tasks, models)

    finished = datetime.now(timezone.utc)
    elapsed_s = (finished - started).total_seconds()
    print(f"\n=== Benchmark run finished in {elapsed_s:.0f}s ===", flush=True)

    # Per-model cost + usage report
    print("\n=== Per-model usage and actual cost ===")
    cost_report = []
    for m in models:
        cost = _cost_usd(m.name, m)
        cost_report.append({
            "model": m.name,
            "n_calls": m.n_calls,
            "n_errors": m.n_errors,
            "input_tokens": m.total_input,
            "output_tokens": m.total_output,
            "reasoning_tokens": m.total_reasoning,
            "cost_usd": round(cost, 4),
        })
        print(
            f"  {m.name:22s} calls={m.n_calls:4d} err={m.n_errors:2d} "
            f"in={m.total_input:7d} out={m.total_output:6d} "
            f"reasoning={m.total_reasoning:7d} cost=${cost:.4f}"
        )
    total_cost = sum(c["cost_usd"] for c in cost_report)
    print(f"  {'TOTAL':22s}                       cost=${total_cost:.4f}")

    # Write to BigQuery
    print("\n=== Writing to BigQuery ===")
    try:
        written = write_rows(rows, project=project)
        print(f"  wrote {written} rows to {project}:cacr_results.benchmark_*", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  BQ write FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # Still emit the cost report below so we don't lose it.

    # Persist a structured cost report next to results/
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results",
        f"frontier_run_cost_report_{started.strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    with open(out_path, "w") as f:
        json.dump({
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "elapsed_s": elapsed_s,
            "per_model": cost_report,
            "total_cost_usd": round(total_cost, 4),
        }, f, indent=2)
    print(f"  cost report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
