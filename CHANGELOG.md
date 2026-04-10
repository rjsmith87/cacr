# Changelog

## 2026-04-09

### Initial Framework
- Task ABC (prompt, eval, threshold, family, complexity) and Model ABC (generate, tier, cost_per_token)
- IntentClassification task (5 categories, 10 examples) and JsonExtraction task (schema validation, 5 examples)
- Claude Haiku adapter via Anthropic SDK
- Runner: tasks × models loop with timing, JSONL stdout output

### Multi-Model Support
- Added Gemini Flash adapter (google-genai SDK, direct API)
- Added Gemini Pro adapter (later replaced)
- Added GPT-4o-mini adapter (OpenAI SDK)
- Runner: graceful per-model init errors, continues with available models

### Confidence Calibration
- Self-reported confidence scoring (1-10) via second model call per example
- Pearson correlation (calibration_r) between confidence and eval scores
- Per-difficulty calibration breakdown (easy/medium/hard)

### Code & Security Tasks
- Replaced customer service tasks with CodeReview, SecurityVuln, CodeSummarization
- 15 examples per task with mixed difficulty levels

### Gemini Debugging & Flash Lite
- Fixed: Vertex AI 403 → switched to direct Gemini API with GOOGLE_API_KEY
- Fixed: 503 retry logic (5 attempts, 4s base exponential backoff)
- Fixed: calibration_r=1.0 artifact from 503 dropout small-sample correlation
- Replaced gemini-2.5-pro (perpetual 503) with gemini-2.5-flash-lite
- Flash Lite emerged as cost-optimal model across entire battery

### BigQuery Integration
- bq_writer.py: streaming insert to benchmark_calls + benchmark_summaries tables
- ADC re-authenticated with BigQuery scopes
- User account granted bigquery.dataEditor + bigquery.user + serviceUsageConsumer

## 2026-04-10

### Expanded Task Battery
- 30 examples per task (10 easy / 10 medium / 10 hard)
- Realistic synthetic code with real bug patterns, CVE-style vulnerabilities, obfuscated names

### Pipeline Simulation
- 3-step code review pipeline: severity → bug type → fix
- Three strategies: all-haiku, all-lite, cacr-routed
- Results written to BigQuery pipeline_results table

### Cost Model & Router
- Cascade-aware expected cost formula with retry pricing
- Cost matrix CSV output
- LookupTableRouter (baseline) + CACRRouter (logistic regression)

### Flask API
- 7 endpoints: health, capability-matrix, calibration, pipeline-cost, cost-matrix, route, findings
- Flask + flask-cors + gunicorn

### React Dashboard
- Vite + React + Recharts + Tailwind
- 5 views: Capability Matrix, Calibration Explorer, Pipeline Cost, Router Playground, Model Efficiency

### Infrastructure
- Render deployment config (render.yaml)
- Environment sync script (scripts/sync_env_to_render.py)
- Makefile with benchmark, api-dev, dashboard-dev targets

### Documentation
- README.md, METHODOLOGY.md, CLAUDE.md, CONTEXT.md, FINDINGS.md, CHANGELOG.md

### CVE Case Study (expanded to 12 CVEs)
- 12 real CVEs: Flask, Requests, urllib3, Jinja2, PyJWT, PyYAML, Werkzeug, certifi
- 2-step CVE pipeline: detect → explain, 3 routing strategies, all 4 models
- Key finding: Flash missed 6/12 CVEs (silent failures), Flash Lite detected 12/12
- BQ writer updated with GOOGLE_APPLICATION_CREDENTIALS_JSON for Render deployment

### Render Deployment
- Created personal GCP project (cacr-bq-personal) with SA key for BQ access
- Services: cacr-api (Flask/gunicorn) and cacr-dashboard (Vite static)
- Live URLs: https://cacr-api.onrender.com, https://cacr-dashboard.onrender.com
- Added /health endpoint for Render health checks

### Blog Post
- BLOG_DRAFT.md: "The $0.00000004 Security Scanner" — data-driven writeup of CVE findings

### 4-Step Pipeline with CVE Detection + Escalation Router
- Pipeline expanded from 3 to 4 steps: severity → bug type → CVE detection → fix
- Added GPT-4o-mini as 4th routing strategy (all-gpt4o-mini)
- CACR router escalation logic: if best tier-1 score < 0.6, escalate to cheapest
  tier-2 model scoring > 0.7
- 3 snippets now include security vulnerabilities (SQL injection, XSS, pickle RCE)
- GPT-4o-mini anomalously slow (13.6s) with worst cascade failure rate
- CACR matches Flash Lite cost at lower latency via model reuse
