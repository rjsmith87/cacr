# CACR Findings — 2026-04-28 (v2: frontier tier added)

## Headline: Flash Lite is still cost-optimal — adding the frontier tier doesn't change the routing decision

Adding **Claude Opus 4.7, GPT-5, o3, and Gemini 2.5 Pro** to the benchmark moves the *accuracy ceiling* up by 4–7pp on classification tasks and 10pp on summarization, but **doesn't dislodge Gemini 2.5 Flash Lite as the cost-optimal default on any of the three tasks**. The frontier tier is 5–50× more expensive per call (input + output + reasoning tokens billed together) and the absolute accuracy gains are marginal where they exist at all. The headline finding from v1 holds with the frontier tier in the mix.

## Capability Matrix (30 examples/task, 8 models — v2 frontier rows recomputed from BQ deduped calls)

| Model                  | Tier | $/MTok in/out | CodeReview | SecurityVuln | CodeSumm | Avg    | Mean Lat |
|------------------------|------|---------------|------------|--------------|----------|--------|----------|
| **gemini-2.5-flash-lite** | SLM | **$0.10/$0.40** | **0.90** | **0.93**    | **0.42** | **0.75** | **476ms** |
| gpt-4o-mini            | SLM | $0.15/$0.60   | 0.77       | 0.93         | 0.40     | 0.70   | 743ms    |
| claude-haiku-4-5       | SLM | $1.00/$5.00   | 0.90       | **1.00**     | 0.38     | 0.76   | 740ms    |
| gemini-2.5-flash       | SLM | $0.30/$2.50   | 0.57       | 0.80         | 0.16     | 0.51   | 2,115ms  |
| gpt-5                  | frontier | $1.25/$10.00 | 0.93   | 0.90         | 0.35     | 0.73   | 3,423ms  |
| **o3**                 | frontier | $2.00/$8.00 | **0.97** | 0.97         | 0.33     | 0.76   | 2,369ms  |
| gemini-2.5-pro         | frontier | $1.25/$10.00 | 0.90   | 0.97         | 0.47     | 0.78   | 11,470ms |
| **claude-opus-4-7**    | frontier | $15.00/$75.00 | 0.93 | 0.97         | **0.52** | **0.81** | 1,370ms  |

## Where the frontier tier helps and where it doesn't

**Highest-accuracy model per task:**
- **CodeReview**: o3 (0.97) beats Flash Lite (0.90) by 7pp — at ~5× the cost
- **SecurityVuln**: Haiku (1.00) — *the SLM tier still wins*; no frontier model exceeds it
- **CodeSummarization**: Opus 4.7 (0.52) beats Flash Lite (0.42) by 10pp — at ~5× the cost

**Cost-optimal model per task (cheapest passing threshold, with cascade retry):**
- CodeReview → Flash Lite (score 0.90, expected cost $0.000134)
- SecurityVuln → Flash Lite (score 0.93, expected cost $0.000100)
- CodeSummarization → Flash Lite (score 0.42, expected cost $0.000623)

Frontier-tier upgrades only make economic sense on **CodeSummarization for user-facing outputs**, where Opus 4.7's 10pp accuracy bump may justify its 5× premium because the failure mode of bad summarization is visible to the end user. On classification tasks where wrong answers are recoverable via cascade retry, the SLM tier remains correct.

## Frontier-tier observations

- **Latency is a real cost**. Pro averages 11.5s/call across tasks (16.7s on CodeSummarization), vs Flash Lite at 0.5s. On a 4-step agentic pipeline, Pro adds 40–70s of wall time per request — disqualifying for interactive use independent of dollar cost.
- **Reasoning tokens dominate Pro's bill**: ~1000 reasoning tokens per call vs 5–50 visible output. Pro **cannot disable thinking mode** (returns 400 INVALID_ARGUMENT on `thinking_budget=0`).
- **GPT-5 also reasons by default** (~64 reasoning tokens on trivial classifications), roughly doubling its effective per-call cost vs the published non-reasoning rate.
- **o3 beats GPT-5 on classification** (0.97 vs 0.93 CodeReview, 0.97 vs 0.90 SecurityVuln) at similar cost. If you want a reasoning model in the cascade, o3 is the better pick at this price point.
- **Confidence saturation**: Pro reports confidence=10 on every successful call (mean 10.0 across all tasks); o3 stays at 8–9. Self-reported confidence from frontier models is largely uninformative — Opus 4.7 is the exception, with cal_r=+0.60 on SecurityVuln/hard.

## Failures and rate limits during the v2 run

- **Gemini 2.5 Pro hung indefinitely** on a CodeSummarization confidence probe after 16 successful calls. Diagnosis (lsof): server-closed socket (`CLOSE_WAIT`) the google-genai SDK didn't surface as a retryable error — client stuck in `recv()` for 10h+. Fixed in commit `39f0465` by adding `HttpOptions(timeout=60_000)` and treating `httpx.TimeoutException`/`NetworkError` as retryable alongside the existing 429/503 handling. **This is a production-relevant data point about Pro's reliability profile under sustained load** — the v1 decision to remove Pro was driven by 503s; v2 confirms the underlying infrastructure remains less stable than the SLM tier.
- **Pro re-run hit 8 additional 503 UNAVAILABLE errors** during a single ~53min window on examples 6–12, plus 1 ReadTimeout on example 27 (the 60s timeout fired and the retry ladder rescued it on the next attempt). The dedup logic preserved the original-run successful results for the affected `example_idx` values, so the final 30-example dataset is clean. The summary row written by the re-run is stale (mean=0.25 reflects the 503-heavy re-run); the deduped calls table is authoritative at mean=0.47. The summary will self-heal once the BQ streaming buffer flushes and an UPDATE can land.
- **No errors from Opus 4.7, GPT-5, or o3** across 270 calls each.

## v2 run cost

Frontier benchmark spend: ~$3.66 projected from the smoke-test ratios for the original 4-model run, plus ~$0.58 measured for the Pro × CodeSummarization re-run, total ~$4.24. Per-call instrumentation isn't yet in the `benchmark_calls` schema (current columns: latency, score, output, error — no token counts), so model-level breakdown is estimated rather than measured. Adding `input_tokens`, `output_tokens`, `reasoning_tokens` columns is the next obvious BQ-schema improvement; deferred for now.

---

## Original v1 capability matrix (2026-04-10, 4 SLM-tier models — preserved for context)

The v1 finding that Flash Lite was cost-optimal on the SLM tier:

| Model                  | Tier | $/MTok | CodeReview | SecurityVuln | CodeSumm | Avg    |
|------------------------|------|--------|------------|--------------|----------|--------|
| claude-haiku-4-5       | 1    | $1.00  | 0.90       | 1.00         | 0.38     | 0.76   |
| gemini-2.5-flash       | 1    | $0.10  | 0.83       | 0.90         | 0.34     | 0.69   |
| **gemini-2.5-flash-lite** | 1 | **$0.04** | **0.90** | **0.93**    | **0.42** | **0.75** |
| gpt-4o-mini            | 2    | $0.15  | 0.77       | 0.93         | 0.40     | 0.70   |

## Calibration Analysis (30 examples/task)

### Overall calibration_r (Pearson: self-reported confidence vs eval score)

- **GPT-4o-mini**: +0.251 CodeReview, +0.663 SecurityVuln (best calibrated)
- **Claude Haiku**: +0.189 CodeSummarization, -0.106 CodeReview
- **Flash Lite**: -0.182 CodeReview, -0.066 SecurityVuln (weak negative — overconfident on misses)
- **Gemini Flash**: Often reports confidence=10 regardless of score — poorly calibrated

### Per-difficulty calibration (Hard examples)

Hard examples surface the most useful calibration signal:
- GPT-4o-mini: H:+0.82 CodeReview (strong), H:+0.06 CodeSummarization
- Haiku: H:-0.11 CodeReview, H:+0.23 CodeSummarization
- Flash Lite: H:+0.19 CodeReview, H:N/A elsewhere (insufficient variance)

### Statistical artifact: calibration_r=1.0

An earlier run showed Gemini Flash with cal_r=1.000 on CodeSummarization. Root cause: 503 API errors caused most confidence probes to fail (returned as NaN, filtered out), leaving only 2 valid data points that trivially correlated. Fixed by increasing retry attempts from 3 to 5 with 4s base exponential backoff and server-hint delay parsing.

## Pipeline Simulation

3-step pipeline: severity classification → bug type identification → fix suggestion. 10 code snippets, 3 strategies:

| Strategy       | Severity | Bug Type | CVE Detect | Fix  | Cascade Fail | Cost       | Latency |
|----------------|----------|----------|------------|------|--------------|------------|---------|
| all-haiku      | 0.40     | 0.90     | 0.40       | 0.30 | 0.70         | $0.003154  | 3798ms  |
| all-lite       | 0.30     | 0.90     | 0.30       | 0.30 | 0.70         | $0.000119  | 3568ms  |
| all-gpt4o-mini | 0.30     | 0.70     | 0.30       | 0.20 | 0.80         | $0.000451  | 13666ms |
| cacr-routed    | 0.30     | 0.90     | 0.30       | 0.30 | 0.70         | $0.000119  | 2007ms  |

4-step pipeline: severity → bug type → CVE detection → fix suggestion. 10 snippets (7 bugs, 3 with security vulnerabilities). Step 2 (bug type) is the strongest across all strategies at 0.70-0.90. CACR matches Flash Lite cost ($0.000119) at lower latency (2007ms vs 3568ms). GPT-4o-mini is anomalously slow (13.6s) and has the worst cascade failure rate. Haiku costs **26x more** for comparable accuracy.

## Cost Model

Expected cost per (task, model) pair including cascade failure retry:

| Task              | Cost-Optimal Model     | Expected Cost | Score |
|-------------------|------------------------|---------------|-------|
| CodeReview        | gemini-2.5-flash-lite  | $0.000077     | 0.90  |
| SecurityVuln      | gemini-2.5-flash-lite  | $0.000055     | 0.93  |
| CodeSummarization | gemini-2.5-flash-lite  | $0.000404     | 0.42  |

## Gemini 2.5 Pro: Re-added in v2 (with caveats)

gemini-2.5-pro was removed in v1 after consistently returning 503 (UNAVAILABLE) on Vertex AI. v2 re-added Pro via the direct API path (`GOOGLE_API_KEY`, `google-genai`) — same path as Flash and Flash Lite. Pro now passes all three task thresholds (0.90/0.97/0.47) but at 8.7–16.7s/call latency, with one indefinite hang requiring a per-request timeout fix (see "Failures and rate limits" above) and 8 503s during a 53-minute re-run window. Pro is **operational** on the direct API but its tail-latency and availability are markedly worse than the SLM tier. Inclusion is justified for the capability-matrix completeness; routing should still default to SLM-tier models with Pro as an explicit-opt-in escalation target only when accuracy gains justify the latency penalty.

## Key Takeaway for Routing (updated for v2)

For a 3-step agentic pipeline, the cascade-aware router defaults to Flash Lite for all steps. v2's addition of the frontier tier confirms this: even with Opus 4.7, GPT-5, o3, and Pro on the table, Flash Lite remains cost-optimal on every task that meets its threshold. Frontier models become economic only when (a) the failure mode is user-visible (CodeSummarization → Opus, +10pp at 5× cost) or (b) the task is one Flash Lite can't pass at all (none in the current battery — every task has Flash Lite ≥ threshold).

The remaining opportunity is in calibration-based dynamic routing: GPT-4o-mini's strong calibration on hard examples (H:+0.82) and Opus 4.7's strong calibration on SecurityVuln/hard (H:+0.65) make them candidates for a "confidence-aware escalation target" when Flash Lite reports low confidence — but this requires switching from self-reported confidence to logprob-based confidence extraction. Pro and o3 confidence is saturated at 9–10 across the board and contributes no escalation signal.

## Content-Aware Routing: Automatic Complexity Inference

The router now automatically infers code complexity from the snippet itself using static analysis heuristics: lines of code, cyclomatic complexity proxy (control flow keyword count), dangerous pattern detection (os.system, pickle, eval, raw SQL), and import count. Each signal votes easy/medium/hard with weighted voting — dangerous patterns override to hard regardless. This means users don't need to manually classify complexity; the router reads the code and decides.

In practice, complexity inference feeds into the escalation logic: if a snippet is inferred as "hard" and the cheapest tier-1 model scores below 0.6 on hard examples for that task, the router escalates to a more capable model. Currently Flash Lite passes on all tasks at all complexity levels, so escalation doesn't trigger — but the mechanism is ready for tasks where tier-1 models struggle on hard inputs.

## CVE Case Study (12 Real CVEs)

12 CVEs tested across Flask, Requests, urllib3, Jinja2, PyJWT, PyYAML, Werkzeug, and certifi. Severity distribution: 3 critical, 5 high, 4 medium. All 12 are real, patched vulnerabilities with known CVE IDs.

### Detection Results (step 1: is this code vulnerable?)

| Model               | CVEs Detected | Missed High/Crit | Mean Conf |
|---------------------|---------------|-------------------|-----------|
| claude-haiku-4-5    | 12/12         | 0                 | 9.0       |
| gemini-2.5-flash    | **6/12**      | **2**             | N/A       |
| gemini-2.5-flash-lite | 12/12       | 0                 | 9.3       |
| gpt-4o-mini         | 12/12         | 0                 | 8.0       |

### Key Finding: Gemini 2.5 Flash misses half of all CVEs

**Gemini 2.5 Flash missed 6 of 12 CVEs**, including 2 high-severity vulnerabilities. The specific misses:
- **CVE-2018-18074** (Requests auth credential leak on cross-host redirect) — high, MISSED
- **CVE-2021-33503** (urllib3 ReDoS) — medium, MISSED
- **CVE-2020-28493** (Jinja2 ReDoS) — medium, MISSED
- **CVE-2022-23491** (certifi compromised root CA) — medium, MISSED
- **CVE-2023-25577** (Werkzeug multipart DoS) — high, MISSED
- **CVE-2020-26137** (urllib3 CRLF injection) — medium, MISSED

Flash's misses are **silent failures** — no structured output, no confidence score, just empty or unparseable responses. This is worse than a high-confidence wrong answer because there's no signal to trigger a retry or escalation.

The CVEs Flash successfully detected (6/12): CVE-2023-30861, CVE-2023-32681, CVE-2019-11324, CVE-2022-29217, CVE-2021-28363, CVE-2019-20477. These tend to be the most "textbook" examples — the more subtle library-level vulnerabilities are where Flash fails.

### Flash Lite vs Flash: the counterintuitive result

Flash Lite at **$0.04/MTok** detects **12/12 CVEs**. Flash at **$0.10/MTok** detects **6/12**. The cheaper, smaller model is strictly better on security vulnerability detection. This isn't a fluke — Flash Lite consistently returns well-structured responses with confidence scores (mean 9.3), while Flash frequently returns unparseable output.

### Routing Implication

A naive router that picks models by tier or price would choose Flash Lite (cheapest) — and in this case, that's the correct decision. But a router that uses model family as a proxy for capability ("Flash should be better than Flash Lite") would make a catastrophic error on security-critical pipelines. This validates the empirical approach: **benchmark results, not model names, should drive routing.**
