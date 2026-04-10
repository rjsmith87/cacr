# CACR — Claude Code Project Briefing

## What this is

CACR (Cascade-Aware Confidence Routing) is an empirical framework for finding the cheapest LLM that won't break a multi-step agentic pipeline. It benchmarks models on code-focused tasks, measures confidence calibration, and computes cascade-aware cost models.

## Architecture

```
runner.py              → Benchmark runner (tasks × models → JSONL + BigQuery)
tasks/                 → Task battery: CodeReview, SecurityVuln, CodeSummarization (30 each)
models/                → Adapters: ClaudeHaiku, GeminiFlash, GeminiFlashLite, GPT4oMini
pipelines/             → 4-step code review pipeline + CVE detection pipeline
router/cost_model.py   → Expected cost with cascade failure pricing
router/policy.py       → LookupTableRouter (with escalation) + CACRRouter
router/complexity.py   → Auto-infer easy/medium/hard from code via static analysis
api/main.py            → Flask API (7 endpoints, BQ-backed)
dashboard/             → React + Vite + Recharts + Tailwind
results/bq_writer.py   → BigQuery streaming insert
```

## Current state

### What's working
- Full benchmark: 4 models × 3 tasks × 30 examples = 360 calls per run
- Confidence self-scoring with Pearson calibration metric
- Per-difficulty calibration breakdown (easy/medium/hard)
- BigQuery ingestion (benchmark_calls, benchmark_summaries, pipeline_results)
- Cost matrix generation + CSV export
- Pipeline simulation (all-haiku, all-lite, all-gpt4o-mini, cacr-routed) — 4 steps including CVE detection
- CVE detection case study: 12 real CVEs, Flash missed 6/12, Flash Lite 12/12
- Automatic complexity inference from code (router/complexity.py)
- Flask API with 8 endpoints (including /api/route with auto-complexity)
- React dashboard (5 views) deployed on Render

### What needs attention
- Gemini models hit 503s under load — retry logic (5 attempts, 4s base backoff) helps but doesn't eliminate
- Severity classification (pipeline step 1) has low accuracy across all models — the gold labels may need revision
- CACR router trained but trivial (Flash Lite is cost-optimal everywhere, so the LogReg just predicts Flash Lite)
- Render deployment needs GCP service account JSON — org policy blocks key creation, documented in OVERNIGHT_ISSUES.md

## Key decisions and why

1. **Replaced Gemini 2.5 Pro with Flash Lite**: Pro was consistently 503ing. Flash Lite turned out to be the star — matches Haiku at 25x lower cost.
2. **Pearson r for calibration**: Simple, interpretable, correctly handles degenerate cases (zero variance → None). Alternatives considered: Brier score (requires probabilities), ECE (requires binning).
3. **Flask over FastAPI**: User preference. Using gunicorn for production.
4. **Direct Gemini API over Vertex AI**: ADC credentials lacked aiplatform.endpoints.predict permission. GOOGLE_API_KEY works directly.
5. **Confidence as second API call**: Adds latency but works across all providers. Future: logprob extraction.

## Environment

- Python 3.13, venv at ./venv
- API keys in .env (ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, GCP_PROJECT)
- BigQuery dataset: cacr_results (tables: benchmark_calls, benchmark_summaries, pipeline_results)
- ADC for BQ requires `gcloud auth application-default login` with bigquery scope

## What to work on next

1. Expand to 100+ examples per task for statistical significance
2. Add logprob-based confidence extraction
3. Train a non-trivial CACR router (add models where Flash Lite fails)
4. Fix pipeline step 1 gold labels
5. Render deployment (service account workaround)
