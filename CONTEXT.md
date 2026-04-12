# CACR — Context Briefing

## What CACR is

CACR (Cascade-Aware Confidence Routing) is a framework I built to answer: **which LLM should handle each step in a multi-step agentic pipeline to minimize cost without breaking accuracy?**

The key insight is that cascade failures are expensive. If a cheap model gets step 1 wrong, steps 2 and 3 are wasted — and you retry with an expensive model anyway. CACR accounts for this by computing expected cost inclusive of retry costs.

## The thesis

You don't need GPT-4 or Claude Sonnet for every LLM call in a pipeline. For classification tasks (bug detection, vulnerability identification), the cheapest models match the most expensive ones. The savings compound in multi-step pipelines: a 4-step pipeline with Flash Lite costs 26x less than one with Haiku, with comparable accuracy.

## Current results

- **4 models benchmarked**: Claude Haiku, Gemini 2.5 Flash, Gemini 2.5 Flash Lite, GPT-4o-mini
- **3 code-focused tasks**: CodeReview (bug type), SecurityVuln (OWASP), CodeSummarization (ROUGE-L)
- **30 examples per task** (10 easy / 10 medium / 10 hard)
- **Headline finding**: Flash Lite ($0.04/MTok) matches Haiku ($1.00/MTok) on classification and leads on summarization
- **Calibration**: GPT-4o-mini is best calibrated (knows when it's uncertain); Flash is worst (always says 10)
- **CVE case study**: 12 real CVEs — Flash Lite detected 12/12, Gemini Flash missed 6/12 (silent failures)
- **Pipeline simulation**: 4-step pipeline (severity → bug type → CVE detect → fix), 4 strategies — All-Haiku costs $0.003154 vs CACR at $0.000119 (26x cheaper)
- **Auto complexity**: Router infers easy/medium/hard from code via static analysis (LOC, control flow, dangerous patterns, imports)

## Tech stack

- Python 3.13, Flask API (gunicorn), React + Recharts + Tailwind dashboard
- BigQuery for results storage (benchmark_calls, benchmark_summaries, pipeline_results, cve_results)
- Anthropic SDK (Claude Sonnet for ELI5 explanations), google-genai SDK, OpenAI SDK
- scikit-learn for the CACR logistic regression router
- Playwright for E2E UI testing (20 tests across 6 tabs)
- Render for deployment (API + static dashboard)

## Dashboard (6 tabs)

- **Capability Matrix**: heatmap of scores, fixed-position tooltip with getBoundingClientRect()
- **Calibration Explorer**: scatter plot + AI-powered ELI5 panel
- **Cascade Cost Model**: expected cost matrix with cascade failure pricing formula
- **Pipeline Cost**: 4-strategy comparison with cost as hero metric, callout banner
- **Router Playground**: paste code → auto complexity inference → routing decision with ELI5
- **Model Efficiency**: score/cost ratio bar chart per model per task

All tabs have "What does this mean?" ELI5 panels powered by Claude Sonnet via POST /api/explain. Panels have 25s AbortController timeout to handle Render cold starts gracefully.

## Render deployment

- **API**: https://cacr-api.onrender.com — Flask + gunicorn, env vars synced via Render API
- **Dashboard**: https://cacr-dashboard.onrender.com — Vite static site with SPA rewrite rule
- **GCP auth**: GOOGLE_APPLICATION_CREDENTIALS_JSON env var (SA key JSON from personal project cacr-bq-personal, cross-project BQ access to project-92dd6ac6-23b0-47de-bb6)
- **Cache headers**: index.html no-cache, /assets/* immutable + 1yr (content-hashed filenames)
- **Deploy**: clearCache required for dashboard updates due to Vite content hashing

## Key technical decisions

- **fmt$() cost formatting**: always toFixed() with enough decimals for 3 significant digits — no scientific notation in the UI ($0.000276 not $2.76e-4)
- **ELI5 timeout**: 25s AbortController on all ELI5 panels — shows "Request timed out — try Refresh" instead of spinning indefinitely on cold starts
- **Tooltip positioning**: position:fixed via getBoundingClientRect() — completely outside table flow, no overlap/clipping
- **Build cache busting**: __BUILD_TS__ define in vite.config.js ensures unique bundle hashes per deploy

## Salesforce angle

This framework directly demonstrates skills relevant to Salesforce's AI platform work:
- Multi-model routing and cost optimization
- Empirical evaluation methodology (30 examples × 3 tasks × 4 models)
- Production pipeline architecture with cascade failure modeling
- Full-stack implementation (Python backend, React frontend, cloud infrastructure)
- E2E testing with Playwright, CI/CD with GitHub Actions
