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
git clone <repo> && cd slm-router
python -m venv venv && source venv/bin/activate
pip install -r requirements-api.txt
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
api/main.py            # Flask API — 7 endpoints backed by BigQuery
dashboard/             # React + Recharts + Tailwind dashboard
results/               # BigQuery writer + cost matrix CSV
```

## Key Finding

For a 3-step agentic pipeline (classify → identify → fix), CACR routes all steps to Flash Lite — saving 25x per token vs Haiku with no accuracy loss on classification. The cost model accounts for cascade failures: when a cheap model fails step 1, the retry cost of a Haiku fallback is still cheaper than running Haiku on every call.

## Methodology

See [METHODOLOGY.md](METHODOLOGY.md) for the full technical writeup.

## Dashboard

The React dashboard provides:
- **Capability Matrix** — heatmap of scores across models and tasks
- **Calibration Explorer** — confidence vs accuracy scatter plots per model
- **Pipeline Cost Calculator** — interactive routing strategy comparison
- **Router Playground** — test the CACR router on custom prompts
- **Model Efficiency** — score/cost ratio visualization
