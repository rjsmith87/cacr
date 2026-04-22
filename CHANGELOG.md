# Changelog

## 2026-04-14

- Pre-registered CVE study success criteria and thresholds in the
  BigQuery schema: `dangerous_rate`, `silent_miss_rate`, 10-bin ECE,
  `overconfidence_score`, and RouteLLM shadow decisions.
- Runner: smoke test rerun, Flash thinking tokens disabled,
  `max_tokens` raised to 1024, rate-limit pacing tuned.

## 2026-04-12

- Repo audit and cleanup (8 fixes):
  - `requirements.txt` added for runner deps; `requirements-api.txt`
    kept for the API.
  - `render.yaml` renamed `GOOGLE_APPLICATION_CREDENTIALS` to
    `GOOGLE_APPLICATION_CREDENTIALS_JSON` to match `bq_writer.py`.
  - `.env.example` documents both the Render JSON path and the
    local ADC path.
  - Removed empty `config.py`; renamed `gemini_pro_adapter.py` to
    `gemini_flash_lite_adapter.py` and updated all imports.
  - `EXPLAIN_MODEL` constant extracted from `api/main.py`.
  - `/api/route` now consumes inferred complexity via `CACRRouter`
    with a `LookupTableRouter` fallback.
  - `tests/test_python.py` added (14 tests); `python-ci.yml` runs
    import smoke test + pytest on push/PR to main.
  - `runtime.txt` pins `python-3.13.2`; README documents the
    720-vs-360 call doubling and input-token-only pricing caveats.

## 2026-04-10

- Task battery expanded to 30 examples per task (10 easy / 10 medium
  / 10 hard) across CodeReview, SecurityVuln, and CodeSummarization.
- Pipeline simulation: severity → bug type → CVE detection → fix,
  with four strategies (all-haiku, all-lite, all-gpt4o-mini, cacr).
- CVE case study: 12 real Python CVEs across Flask, Requests,
  urllib3, Jinja2, PyJWT, PyYAML, Werkzeug, and certifi. Two-step
  pipeline (detect → explain).
- Router: `LookupTableRouter` baseline plus `CACRRouter`
  (scikit-learn logistic regression). Escalation rule: if best
  tier-1 score < 0.6 on a task, escalate to the cheapest tier-2
  model scoring > 0.7.
- Automatic complexity inference in `router/complexity.py`: LOC,
  control-flow keyword count, import count, and dangerous-pattern
  override (`os.system`, `pickle`, `eval`, raw SQL). Weighted vote
  per signal.
- Flask API: 10 endpoints, BigQuery-backed, Claude Sonnet ELI5 via
  `POST /api/explain`.
- React dashboard: Vite + React 19 + Recharts + Tailwind 4, six
  tabs (Capability Matrix, Calibration Explorer, Cascade Cost Model,
  Pipeline Cost, Router Playground, Model Efficiency).
- Render deployment: `cacr-api` (Flask/gunicorn) and `cacr-dashboard`
  (Vite static site). Environment sync via
  `scripts/sync_env_to_render.py`. `/health` endpoint for Render
  health checks.

## 2026-04-09

- Initial framework: `Task` and `Model` abstract base classes;
  runner loop with JSONL stdout output.
- Four model adapters: Claude Haiku (Anthropic SDK), Gemini 2.5
  Flash and 2.5 Flash Lite (google-genai, direct Gemini API),
  GPT-4o-mini (OpenAI SDK). Gemini 2.5 Pro was replaced with Flash
  Lite after persistent 503s.
- Self-reported confidence scoring (1 to 10) via a second model call
  per example. Pearson r between confidence and eval score, computed
  overall and per difficulty.
- BigQuery ingestion: `benchmark_calls` and `benchmark_summaries`
  tables via `bq_writer.py`.
- Gemini retry logic: 5 attempts, 4s base exponential backoff, with
  server-hint delay parsing. Fixed a `cal_r=1.000` artifact caused by
  503 dropouts leaving too few valid confidence data points.
