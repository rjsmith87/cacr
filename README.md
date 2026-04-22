# CACR: Cascade-Aware Confidence Routing

Finding the cheapest LLM that won't break an agentic pipeline. Empirical
benchmarks of accuracy, cost, and dangerous rate.

## Live

- Dashboard: https://cacr-dashboard.onrender.com
- API health: https://cacr-api.onrender.com/health

## The problem

Modern agent stacks chain multiple LLM calls in a row. A code review
agent might classify bug severity, then name the bug type, then draft
a fix. Each step has its own cost and its own failure rate. The
per-call cost you see on a pricing page is not the cost you actually
pay once step 1 is wrong and the pipeline has to retry from scratch.

The common advice is "just use a smaller, cheaper model". That advice
is right on average and wrong in the specific cases that matter. A
smaller model that returns structured output 95% of the time looks
great on a one-shot eval and quietly corrupts a three-step pipeline.
Worse, some failure modes are silent. The model returns empty or
unparseable output with no confidence signal, so nothing downstream
knows to escalate.

Picking a model for a pipeline is a routing decision, not a vibes
check. The routing decision needs evidence. You need to know each
model's accuracy on each step, its cost per call, and how often it
fails confidently on inputs where a wrong answer is actually dangerous.
CACR is my attempt to produce that evidence for the code-review and
security subtasks I care about.

## What it measures

Three metrics, one per call and rolled up per (model, task):

**Accuracy.** For the classification tasks (code review, security
vulnerability) this is exact match against a gold label. For code
summarization it is ROUGE-L F1 against a reference summary. Models
also self-report a confidence score from 1 to 10 after each answer, and I
compute Pearson r between confidence and score as a calibration
signal.

**Cost.** Expected cost per call in USD, using each provider's
published input-token price. The router's cost model extends this
with cascade-aware pricing: when a cheap model fails step 1, the
retry at a more expensive fallback still has to pay for the downstream
steps. That compounding is what the model name on a pricing page
doesn't show you.

**Dangerous rate.** The one that actually matters. On the CVE case
study, this is the fraction of high- or critical-severity
vulnerabilities the model failed to flag. A model that quietly misses
a critical CVE is worse than one that refuses and escalates, because
the pipeline downstream has no signal that anything went wrong. A
sub-metric, `overconfident_miss`, counts the cases where the model
missed a high-severity CVE *and* reported confidence 8 or higher.
Those are the silent failures. The whole point of routing by evidence
is to avoid running a pipeline on a model with a high dangerous rate
on your task, no matter how good the accuracy number looks in
aggregate.

## Case study: 12 CVEs

The CVE battery is small. 12 real, patched Python CVEs across
requests, urllib3, Jinja2, PyJWT, PyYAML, Werkzeug, certifi, and
Flask. Severity mix: 3 critical, 5 high, 4 medium. n=1 per CVE, not
30. I'm deliberately not padding this number. A 12-CVE battery is
enough to make one finding stick and not enough to make capability
claims beyond it. Expanding the battery is on the roadmap.

Step 1 of the CVE pipeline asks each model: is this code vulnerable,
what severity, what's your confidence. Results:

| Model                 | Detected | Missed high/critical | Mean confidence |
|-----------------------|----------|----------------------|-----------------|
| claude-haiku-4-5      | 12/12    | 0                    | 9.0             |
| gemini-2.5-flash      | 6/12     | 2                    | N/A             |
| gemini-2.5-flash-lite | 12/12    | 0                    | 9.3             |
| gpt-4o-mini           | 12/12    | 0                    | 8.0             |

Gemini 2.5 Flash missed half of them. Its failure mode on the misses
was unparseable output with no confidence score at all, which is why
mean confidence is N/A. Gemini 2.5 Flash Lite, priced at 2.5x less,
caught all 12. A router that picked models by family ("Flash beats
Flash Lite") would make a bad decision on this task. A router with
the dangerous-rate number in front of it would not.

The broader 4-model, 3-task, 30-example-per-task battery is where
the cost story lives:

| Model                 | Tier | $/MTok | CodeReview | SecurityVuln | CodeSumm | Avg  |
|-----------------------|------|--------|------------|--------------|----------|------|
| claude-haiku-4-5      | 1    | $1.00  | 0.90       | 1.00         | 0.38     | 0.76 |
| gemini-2.5-flash      | 1    | $0.10  | 0.83       | 0.90         | 0.34     | 0.69 |
| gemini-2.5-flash-lite | 1    | $0.04  | 0.90       | 0.93         | 0.42     | 0.75 |
| gpt-4o-mini           | 2    | $0.15  | 0.77       | 0.93         | 0.40     | 0.70 |

Flash Lite matches Haiku on code review (0.90), comes within 0.07 on
security vulnerability classification (0.93 vs 1.00), and leads all
four on code summarization. It is the cost-optimal choice on every
task in the battery at 25x cheaper than Haiku per input token.

Caveats the numbers hide:

- Prices are input-token only, as of April 2026. Output tokens are
  3 to 5x more expensive. The `$/MTok` column is a routing signal, not
  a billing forecast.
- Providers don't guarantee determinism at `temperature=0.0`. Reruns
  drift by a few percentage points per task.
- Calibration Pearson r is noisy at n=30 and especially at n=10 per
  difficulty bucket. Treat the per-difficulty breakdown as
  directional.
- The formal `dangerous_rate` metric and 10-bin ECE are pre-registered
  in the BigQuery schema but computed today only via the CVE
  pipeline's `missed_high_severity` and `overconfident_miss` proxies.
  Full ECE and per-(model, task) dangerous-rate rollups land with the
  expanded CVE battery.

## Architecture

```
runner.py              Full benchmark: tasks x models x examples, writes JSONL + BigQuery
tasks/                 CodeReview, SecurityVuln, CodeSummarization (30 examples each)
tasks/cve_detection/   12 real CVE snippets with gold labels
models/                Adapters: ClaudeHaiku, GeminiFlash, GeminiFlashLite, GPT4oMini
pipelines/             Multi-step pipelines (code review, CVE detection)
router/
  cost_model.py        Expected cost with cascade failure pricing
  policy.py            LookupTableRouter + CACRRouter (scikit-learn logistic regression)
  complexity.py        Static-analysis inference of easy/medium/hard
api/main.py            Flask API, 10 endpoints, BigQuery-backed
dashboard/             React 19 + Vite + Recharts + Tailwind 4
results/bq_writer.py   BigQuery streaming insert, schema evolution
```

A full run of `runner.py` makes 4 models × 3 tasks × 30 examples =
360 primary calls, plus a second confidence-probe call per example,
for ~720 API calls total. Replacing the second call with logprob
extraction is on the roadmap.

## Stack

- Python 3.13.2 (pinned in `runtime.txt`)
- anthropic, openai, google-genai for model calls
- Flask + flask-cors + gunicorn for the API
- scikit-learn for the CACR logistic-regression router
- google-cloud-bigquery for results storage
- React 19, Vite, Recharts, Tailwind 4 for the dashboard
- Playwright for dashboard E2E tests, pytest for Python tests
- Render for hosting (API and dashboard as separate services)
- GitHub Actions for Python and UI CI

## Running locally

The benchmark, API, and dashboard each run on their own. You only
need the full stack if you want to reproduce the dashboard end to
end.

```bash
git clone https://github.com/rjsmith87/cacr.git
cd cacr

python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt          # benchmark runner
pip install -r requirements-api.txt      # API + router

cp .env.example .env                     # fill in API keys
```

Required keys in `.env`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`. For BigQuery writes also set `GCP_PROJECT` and run
`gcloud auth application-default login` with the scopes listed in
`.env.example`. Without a GCP project the benchmark still runs and
prints JSONL to stdout.

Benchmark and pipeline runs:

```bash
python runner.py                         # 4 models x 3 tasks x 30 examples
python pipelines/cve_pipeline.py         # 12-CVE case study
python pipelines/code_review_pipeline.py # 4-step pipeline simulation
```

API and dashboard:

```bash
make api-dev                             # gunicorn on :8000
make dashboard-dev                       # vite on :5173
```

Tests:

```bash
pytest tests/test_python.py              # 14 tests, import + unit
cd dashboard && npx playwright test      # E2E against a running dashboard
```

## Why this exists

I kept running into this at work. A team ships an agent, picks a
model because it's the one they already have an API key for, and
nobody measures whether a cheaper model would have been fine. Or
they do measure it on a single-shot eval that doesn't capture how
the model behaves inside a pipeline where step 1's mistake poisons
steps 2 and 3. The "just use a smaller model" reflex fails quietly
in exactly the cases where it matters most, which is usually
something security-adjacent.

CACR is a personal research project built to convince myself that
empirical routing is worth the plumbing. It is not a library anyone
should adopt today. It is an argument: given a task family, you can
rank models by a cost metric that includes cascade failures and a
dangerous-rate metric that counts silent high-severity misses, and
the ranking often puts the cheap model at the top. The 12-CVE study
is the smallest honest version of that argument I could build.

## Roadmap

- Expand the CVE battery to 50+ CVEs across Python, Java, and
  JavaScript, with CVSS-banded and OWASP-aligned gold labels, so
  per-(model, CVE-class) dangerous-rate rollups have real sample
  sizes.
- Replace the second confidence-probe call with logprob extraction
  to halve the per-benchmark API cost and drop the ~720-call
  doubling.
- Add a RouteLLM baseline as a direct comparator for the
  dangerous-rate metric, using the same CVE inputs.
- Ship `cacr route <prompt>` as a CLI wrapper around the trained
  router so the routing decision can be tried against real inputs
  outside the dashboard.
