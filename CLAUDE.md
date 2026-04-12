# CACR — Claude Code Project Briefing

## What this is

CACR (Cascade-Aware Confidence Routing) is an empirical framework for finding the cheapest LLM that won't break a multi-step agentic pipeline. It benchmarks models on code-focused tasks, measures confidence calibration, and computes cascade-aware cost models.

## Architecture

```
runner.py              → Benchmark runner (tasks × models → JSONL + BigQuery)
tasks/                 → Task battery: CodeReview, SecurityVuln, CodeSummarization (30 each)
tasks/cve_detection/   → 12 real CVE examples (Flask, Requests, urllib3, PyJWT, etc.)
models/                → Adapters: ClaudeHaiku, GeminiFlash, GeminiFlashLite, GPT4oMini
pipelines/             → 4-step code review pipeline + CVE detection pipeline
router/cost_model.py   → Expected cost with cascade failure pricing
router/policy.py       → LookupTableRouter (with escalation) + CACRRouter
router/complexity.py   → Auto-infer easy/medium/hard from code via static analysis
api/main.py            → Flask API (9 endpoints, BQ-backed + /api/explain for ELI5)
dashboard/             → React + Vite + Recharts + Tailwind (6 tabs)
dashboard/tests/       → Playwright E2E tests (20 tests, all passing)
results/bq_writer.py   → BigQuery streaming insert (ADC or SA JSON via env var)
```

## Current state

### What's working
- Full benchmark: 4 models × 3 tasks × 30 examples = 360 calls per run
- Confidence self-scoring with Pearson calibration metric
- Per-difficulty calibration breakdown (easy/medium/hard)
- BigQuery ingestion (benchmark_calls, benchmark_summaries, pipeline_results, cve_results)
- Cost matrix generation + CSV export
- Pipeline simulation: 4 strategies (all-haiku, all-lite, all-gpt4o-mini, cacr-routed) × 4 steps (severity, bug type, CVE detection, fix)
- CVE detection case study: 12 real CVEs, Flash missed 6/12, Flash Lite 12/12
- Automatic complexity inference from code (LOC, control flow, dangerous patterns, imports)
- Router escalation: if cheapest tier-1 model scores < 0.6, escalate to cheapest tier-2 scoring > 0.7
- Flask API with 9 endpoints including POST /api/explain (Claude Sonnet ELI5)
- React dashboard: 6 tabs (Capability Matrix, Calibration Explorer, Cascade Cost Model, Pipeline Cost, Router Playground, Model Efficiency)
- All 6 tabs have AI-powered "What does this mean?" ELI5 panels
- Deployed on Render: https://cacr-api.onrender.com + https://cacr-dashboard.onrender.com
- Playwright E2E tests: 20/20 passing against live Render URL
- GitHub Actions CI: .github/workflows/ui-tests.yml runs on push to main

### What needs attention
- Gemini models hit 503s under load — retry logic (5 attempts, 4s base backoff) helps but doesn't eliminate
- Severity classification (pipeline step 1) has low accuracy across all models — gold labels may need revision
- CACR LogReg router is trivial (Flash Lite is cost-optimal everywhere) — needs tasks where Flash Lite fails to create meaningful routing decisions

## Key decisions and why

1. **Replaced Gemini 2.5 Pro with Flash Lite**: Pro was consistently 503ing. Flash Lite matches Haiku at 25x lower cost.
2. **Pearson r for calibration**: Simple, interpretable, correctly handles degenerate cases (zero variance → None).
3. **Flask over FastAPI**: User preference. Using gunicorn for production.
4. **Direct Gemini API over Vertex AI**: ADC credentials lacked aiplatform.endpoints.predict. GOOGLE_API_KEY works directly.
5. **fmt$() always uses toFixed()**: No scientific notation in the UI — $0.000276 not $2.76e-4. Computes decimal places from log10 for 3 significant digits.
6. **ELI5 panels have 25s timeout**: AbortController prevents infinite spinner on Render cold starts. Shows "Request timed out — try Refresh."
7. **Tooltip uses position:fixed + getBoundingClientRect()**: Completely outside table flow, no overlap/clipping issues.
8. **Dashboard cache: index.html no-cache, assets immutable**: Plus __BUILD_TS__ define in vite.config.js for unique hashes per deploy. clearCache deploy required for dashboard updates.
9. **BQ auth**: GOOGLE_APPLICATION_CREDENTIALS_JSON env var for Render (SA key JSON), falls back to ADC locally.

## Environment

- Python 3.13, venv at ./venv
- Node 20, Playwright for E2E tests
- API keys in .env: ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, GCP_PROJECT
- BigQuery dataset: cacr_results (tables: benchmark_calls, benchmark_summaries, pipeline_results, cve_results)
- Render services: srv-d7cf11rbc2fs73eta09g (API), srv-d7cf147lk1mc7397nd70 (dashboard)
- Deploy: `git push origin main` + clearCache via Render API for dashboard

## What to work on next

1. Expand to 100+ examples per task for statistical significance
2. Add logprob-based confidence extraction (replace second API call)
3. Add harder tasks where Flash Lite fails to create meaningful escalation routing
4. Fix pipeline step 1 gold labels (severity is subjective)
5. Add streaming to ELI5 panels (currently waits for full response)
6. Blog post finalization and publication
