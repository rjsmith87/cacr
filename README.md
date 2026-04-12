# CACR — Cascade-Aware Confidence Routing

**Gemini Flash Lite at $0.04/MTok matches Claude Haiku on code review (0.90) and security vulnerability detection (0.93), while costing 25x less.** CACR finds the cheapest model that won't break your pipeline.

An empirical framework for cost-optimal routing in multi-step agentic pipelines, accounting for model confidence calibration and cascade failure costs.

![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Capability Matrix (30 examples/task, 4 models)

| Model                  | Tier | $/MTok | CodeReview | SecurityVuln | CodeSumm | Avg  |
|------------------------|------|--------|------------|--------------|----------|------|
| claude-haiku-4-5       | 1    | $1.00  | 0.90       | 1.00         | 0.38     | 0.76 |
| gemini-2.5-flash       | 1    | $0.10  | 0.83       | 0.90         | 0.34     | 0.69 |
| **gemini-2.5-flash-lite** | 1 | **$0.04** | **0.90**  | **0.93**    | **0.42** | **0.75** |
| gpt-4o-mini            | 2    | $0.15  | 0.77       | 0.93         | 0.40     | 0.70 |

Flash Lite is cost-optimal on every task in the battery.

## Quick Start

```bash
git clone <repo> && cd cacr
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in API keys

# Run the benchmark
python runner.py

# Start the API
make api-dev

# Start the dashboard
make dashboard-dev
```

## Architecture

```
runner.py              # Benchmark runner — loops tasks × models, writes JSONL + BQ
tasks/                 # Task battery (CodeReview, SecurityVuln, CodeSummarization)
models/                # Model adapters (Haiku, Flash, Flash Lite, GPT-4o-mini)
pipelines/             # Multi-step pipeline simulations
router/
  cost_model.py        # Expected cost with cascade failure pricing
  policy.py            # LookupTableRouter + CACRRouter (logistic regression)
  complexity.py        # Auto-infer easy/medium/hard from code via static analysis
api/main.py            # Flask API — 10 endpoints (see below)
dashboard/             # React + Recharts + Tailwind dashboard
results/               # BigQuery writer + cost matrix CSV
```

## Key Finding

For a 3-step agentic pipeline (classify → identify → fix), CACR routes all steps to Flash Lite — saving 25x per token vs Haiku with no accuracy loss on classification. The cost model accounts for cascade failures: when a cheap model fails step 1, the retry cost of a Haiku fallback is still cheaper than running Haiku on every call.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health`                  | Render health check |
| GET  | `/api/health`              | Status, model/task counts, total calls |
| GET  | `/api/capability-matrix`   | Models × tasks heatmap data |
| GET  | `/api/calibration`         | Confidence vs accuracy scatter per model |
| GET  | `/api/pipeline-cost`       | Pipeline strategy comparison |
| GET  | `/api/cost-matrix`         | `cost_matrix.csv` as JSON |
| POST | `/api/route`               | Route a prompt to cost-optimal model |
| GET  | `/api/findings`            | `FINDINGS.md` as markdown |
| POST | `/api/explain-calibration` | Claude ELI5 of calibration data |
| POST | `/api/explain`             | Generic Claude ELI5 endpoint |

## Methodology

See [METHODOLOGY.md](METHODOLOGY.md) for the full technical writeup.

### Methodology Notes

- **API calls are doubled by confidence self-scoring.** Each example triggers a second call to the same model asking it to rate its own confidence 1–10. A "360-call run" (4 models × 3 tasks × 30 examples) therefore makes ~720 API calls. Replacing this with logprob extraction is on the roadmap.
- **Cost figures are input-token-only**, based on each provider's public list price as of **April 2026**. Output tokens (typically 3–5× more expensive) are not included; the published `$/MTok` numbers are a routing signal, not a billing forecast. Refresh the constants in `models/*_adapter.py` if pricing changes.
- **Reruns will not exactly reproduce the published numbers.** Models are sampled at `temperature=0.0`, but providers do not guarantee determinism: per-call variation, retries on 503/429, and occasional refusals all introduce drift of a few percentage points per task. Treat the capability matrix as a snapshot, not a fixed-point.

## Dashboard

The React dashboard provides:
- **Capability Matrix** — heatmap of scores across models and tasks
- **Calibration Explorer** — confidence vs accuracy scatter plots per model
- **Pipeline Cost Calculator** — interactive routing strategy comparison
- **Router Playground** — test the CACR router on custom prompts
- **Model Efficiency** — score/cost ratio visualization
