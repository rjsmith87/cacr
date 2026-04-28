# I added the four most expensive frontier models to my router benchmark. The cheap one still won.

I run a small empirical project called CACR — Cascade-Aware Confidence Routing — that benchmarks LLMs on code-focused tasks and measures the *real* cost of using them inside a multi-step pipeline. The original lineup was four small/cheap models: Claude Haiku 4.5, Gemini 2.5 Flash, Gemini 2.5 Flash Lite, and GPT-4o-mini. The headline finding from that v1 run was that Gemini 2.5 Flash Lite, the cheapest model in the lineup at $0.04 per million input tokens, was the cost-optimal default on all three tasks in the battery.

A friend pushed back: *"Sure, the cheap model wins among cheap models. Add the frontier tier and the picture flips."*

So I added Claude Opus 4.7, GPT-5, o3, and Gemini 2.5 Pro — the four most capable, most expensive models on the market — and re-ran the whole benchmark. 720 API calls, ~$4.24 in spend, one infrastructure hang that ate eleven hours of wall time, and one statistical artifact dressed up as a feature.

The picture didn't flip. Flash Lite still wins.

This post explains why, what surprised me, and what changed in the router as a result.

## Why CACR exists

Modern agent stacks chain multiple LLM calls. A code review agent might first classify bug severity, then identify the bug type, then draft a fix. Each step has its own accuracy and its own failure rate. The per-call cost on a pricing page is not the cost you actually pay once step 1 is wrong and the pipeline has to retry from scratch — usually with a more expensive fallback model that also has to redo every downstream step on the corrected input.

The common advice is *"just use a smaller, cheaper model."* That's right on average and wrong in the specific cases that matter. A smaller model that returns structured output 95% of the time looks great on a one-shot eval and quietly corrupts a three-step pipeline. Some failure modes are silent — empty or unparseable output with no confidence signal — so nothing downstream knows to escalate.

Picking a model for a pipeline is a routing decision. The routing decision needs evidence. CACR is my attempt to produce that evidence for code review and security tasks, with the cascade dynamics built into the cost model:

```
expected_cost = (model_cost × tokens) × P(success) + retry_cost × P(failure) × cascade_depth
```

A model that's $0.001 cheaper per call but fails 20% more often is a bad bet inside a four-step pipeline.

## Methodology in 90 seconds

Eight models, three tasks, thirty examples each, two calls per example (answer + confidence probe). 720 API calls per full run, written to BigQuery for analysis.

**Tasks:**
- *CodeReview* — given a buggy Python snippet, classify the bug type (logic_error, null_pointer, off_by_one, resource_leak, race_condition). Exact-match scoring.
- *SecurityVuln* — given a snippet, classify the vulnerability type (sql_injection, xss, path_traversal, hardcoded_secret, insecure_deserialization). Exact-match scoring.
- *CodeSummarization* — given a function, produce a one-sentence summary. ROUGE-L F1 against a reference.

Each task has a 10/10/10 split across easy/medium/hard difficulty. Hard examples are deliberately constructed to require multi-line reasoning, not pattern matching — single-letter variable names, obfuscated control flow, edge cases that turn into off-by-one errors only on close reading.

**Calibration probe.** After each model answers, I ask the same model to rate its own confidence from 1 to 10. I then compute Pearson correlation between confidence and actual eval score. A well-calibrated model shows positive r: it's more confident on the answers it got right.

**Dangerous rate.** On a separate 12-CVE case study, the headline metric is how many high- or critical-severity vulnerabilities the model missed. A silent miss is worse than a high-confidence wrong answer because nothing downstream has a signal to retry.

## The capability matrix

Here's what 720 calls bought (run timestamp `2026-04-28T03:06:05Z`):

| Model                  | Tier     | $/MTok in/out | CodeReview | SecurityVuln | CodeSumm | Avg  | Mean Lat |
|------------------------|----------|---------------|------------|--------------|----------|------|----------|
| **gemini-2.5-flash-lite** | SLM   | **$0.10/$0.40** | **0.90** | **0.93**    | **0.42** | 0.75 | **476ms** |
| gpt-4o-mini            | SLM      | $0.15/$0.60   | 0.77       | 0.93         | 0.40     | 0.70 | 743ms    |
| claude-haiku-4-5       | SLM      | $1.00/$5.00   | 0.90       | **1.00**     | 0.38     | 0.76 | 740ms    |
| gemini-2.5-flash       | SLM      | $0.30/$2.50   | 0.57       | 0.80         | 0.16     | 0.51 | 2,115ms  |
| gpt-5                  | frontier | $1.25/$10.00  | 0.93       | 0.90         | 0.35     | 0.73 | 3,423ms  |
| **o3**                 | frontier | $2.00/$8.00   | **0.97**   | 0.97         | 0.33     | 0.76 | 2,369ms  |
| gemini-2.5-pro         | frontier | $1.25/$10.00  | 0.90       | 0.97         | 0.47     | 0.78 | 11,470ms |
| **claude-opus-4-7**    | frontier | $15.00/$75.00 | 0.93       | 0.97         | **0.52** | **0.81** | 1,370ms |

A few things jumped out.

**The frontier tier raises the ceiling, not the floor.** o3 is the highest scorer on CodeReview at 0.97. Opus 4.7 is the highest scorer on CodeSummarization at 0.52. Pro and o3 tie with Opus on SecurityVuln at 0.97. So if you want raw accuracy, the frontier models do beat the SLMs — by 4–7 percentage points on classification, 10pp on summarization. The bump is real but small.

**The bump is not free.** Per million tokens, Opus is 150x more expensive than Flash Lite on input and 187x on output. o3 is 20x and 20x. GPT-5 and Pro are about 12x and 25x. For a 7-percentage-point CodeReview bump, you're paying 5x more per call (o3 vs. Flash Lite), and that's *before* counting reasoning tokens.

**Reasoning tokens dominate the bill on Pro.** Gemini 2.5 Pro cannot disable thinking mode — passing `thinking_budget=0` to the SDK returns `400 INVALID_ARGUMENT: "This model only works in thinking mode."` On a trivial code-summarization example with a one-line function, Pro burned 996 reasoning tokens to produce a three-token visible answer. That gets billed at the output rate, $10 per million tokens. Pro's effective per-call cost on CodeSummarization is about 4x what the published input rate suggests.

**Latency is a hidden cost.** Pro averages 11.5 seconds per call across the battery, 16.7 seconds on summarization. Flash Lite averages 476 milliseconds. On a four-step pipeline, that's a 40-to-70-second wall-clock difference per request. For interactive use, Pro is disqualified independent of dollar cost.

**Haiku still beats every frontier model on SecurityVuln.** SecurityVuln is the only task in the battery where the SLM tier doesn't just win on cost-adjusted accuracy — it wins outright. Haiku at 1.00 vs. the best frontier score of 0.97. I don't have a clean explanation for this; it might be an artifact of the small (n=30) battery, or the OWASP-aligned categories may favor models trained heavily on security training data. Worth more examples.

## When you actually do want a frontier model

The cost-adjusted analysis is unambiguous on classification: if Flash Lite passes, Flash Lite wins. The case for upgrading narrows to one specific niche.

**CodeSummarization, when the output is user-visible.** Opus 4.7 reaches 0.52 ROUGE-L. Flash Lite tops out at 0.42. That's a 10-point bump at roughly 5x cost. On a task where the failure mode is a bad summary that ships to a human, the cost premium might be defensible — bad summarization is annoying; bad summarization that the user reads is more than annoying. On classification tasks where wrong answers are recoverable via cascade retry, the SLM tier remains correct.

## The Gemini Pro hang

I'm going to tell this story, because I think it's a real production-relevant data point about Pro's reliability profile.

The first frontier run hung for over eleven hours. Process state `S` (interruptible sleep), 0.0% CPU, log file untouched for ten and a half hours. `lsof` on the Python process showed a `CLOSE_WAIT` socket to a Cloudflare IP — the server had closed its half of the connection but the Python `google-genai` SDK was still in `recv()` waiting for data that would never arrive. The SDK's `tenacity`-based retries only fire on errors that surface as `APIError`. A server-closed socket without an error response never escapes `recv()` and never reaches the retry layer.

The fix was straightforward: set `HttpOptions(timeout=60_000)` on the `GenerateContentConfig` and catch `httpx.TimeoutException` and `httpx.NetworkError` in the adapter's retry loop alongside the existing 429/503 handling. 60 seconds is comfortably above Pro's observed 10-32-second range on summarization. The retry ladder caps at three attempts before raising.

The re-run of the affected 14 examples — under the same `run_ts` so BigQuery's idempotent dedup would catch the 16 already-written calls — picked up another 8 transient 503 UNAVAILABLE responses in a 53-minute window, plus one read timeout that the new fix correctly classified as retryable.

The headline isn't "Pro is broken." Pro works. The headline is that Pro's tail latency and availability under sustained load are markedly worse than the SLM tier. Flash Lite ran 270 calls in v2 with zero errors. Pro ran 270 calls in v2 with one indefinite hang requiring a code fix and nine transient errors. If you're routing a customer-facing pipeline, that reliability delta has to be in the cost model.

## The router floor: why 0.70

The original CACR router was a lookup table. For each task, it picked the cheapest model whose mean score passed the per-task threshold (0.6 for the classification tasks, 0.4 for CodeSummarization). The thresholds were chosen task-by-task during development; they reflect "this task is harder so we accept a lower score."

A friend pointed out — accurately — that the router was therefore happily recommending Flash Lite for CodeSummarization at score 0.42, with no warning. 0.42 means the model is wrong more than half the time. Recommending it as if it were a defensible default was lying.

The router now enforces a hard global floor of `MIN_ACCEPTABLE_SCORE = 0.70` on top of any per-task threshold. Why 0.70: below it, the model is wrong more than 30% of the time, which is not acceptable for production deployment of a tool a human will rely on without manually checking each output. The floor is deliberately stricter than every per-task threshold in the original benchmark.

Three branches now:

- **At least one model meets 0.70**: cheapest such model wins. Existing escalation logic is preserved — if the cheapest acceptable pick is borderline (<0.80) and a higher-cost model offers a +0.05 accuracy bump, escalate.
- **No model meets 0.70**: the router still returns the best-available model so callers can proceed, but the response now carries `below_threshold: true` and a `warning` field with text like *"All evaluated models score below 0.70 on {task}. Best available is {model} at score {score}. Consider human review or task reformulation."*
- **No data at all for the task**: same warning treatment.

The dashboard surfaces the warning as a visible amber banner. The Claude-powered "what does this mean?" panel that explains the routing decision used to gush about "rock-bottom pricing" and "passes our minimum standards" for the 0.42 CodeSummarization recommendation. It now switches voice. Here's an actual production-equivalent generation from the new prompt template, on the below-threshold case:

> *"For CodeSummarization, I'm recommending gemini-2.5-flash-lite at a cost of $0.0004, but I need to be upfront: this is not a good situation. All available AI models perform poorly on this task, with the best one only scoring 0.42 out of 1.0 — well below acceptable standards. This model is simply the least-bad option available, not a quality solution. I strongly recommend having a human review any code summaries this AI produces, or consider whether this task should be done by AI at all."*

For a task that *does* pass — CodeReview at 0.90 — the explanation reads normally:

> *"The system chose gemini-2.5-flash-lite because it's the cheapest option that still meets the minimum quality requirement of 0.7 — and it actually scores much higher at 0.90. The cost is extremely low at just $0.000077 (less than a hundredth of a cent). Since this is classified as an "easy" complexity task, using this affordable but capable model makes perfect sense rather than paying more for a premium model you don't need."*

The same prompt template generates both. The difference is one structured field — `warning` — that triggers a different framing block. No banned phrases, no marketing language, no pretending a 0.42 score is fine.

## A separate finding from the original 4-model battery: the CVE case study

Twelve real, patched Python CVEs across requests, urllib3, Jinja2, PyJWT, PyYAML, Werkzeug, certifi, and Flask. n=1 per CVE. Step 1 of the pipeline asks each model: *is this code vulnerable, what severity, what's your confidence.*

| Model                 | Detected (n=1) | Mean confidence |
|-----------------------|----------------|-----------------|
| claude-haiku-4-5      | 12/12          | 9.0             |
| gemini-2.5-flash      | 12/12          | 9.3             |
| gemini-2.5-flash-lite | 12/12          | 9.3             |
| gpt-4o-mini           | 12/12          | 8.0             |

All four SLM-tier models detect all 12 CVEs correctly under normal conditions. **An earlier version of this draft claimed "Gemini 2.5 Flash silently misses 6/12 CVEs."** That finding was retracted: the 6 originally-recorded misses were 503 timeouts and rate-limit failures from the Gemini direct API during the v1 benchmark run — infrastructure noise, not capability. Commit `4867197` flagged this internally at the time, but the public docs took longer to catch up. A fresh sweep of all 12 CVEs in April 2026 returned `vulnerable: yes` with confidence 8–10 on every one, including all six previously listed as "MISSED."

What's left unanswered by n=1 is whether silent failures surface under sustained traffic — which is exactly the regime where the original 503s came from. A scale study (n=30 per CVE, 360 calls total) is queued to test this directly. Results will land in `cve_scale_study.jsonl` / the BigQuery `cve_scale_study` table; if this draft is up but the section above is empty, the study hasn't run yet.

The 12-CVE battery is small. n=1 per CVE is enough to falsify a "Flash misses half" claim and not enough to make new capability claims of its own. Expanding to 50+ CVEs across Python, Java, and JavaScript with CVSS-banded gold labels is on the roadmap.

## What's next

- **Replace the confidence probe with logprobs.** The second API call per example doubles the run cost. Native logprob extraction would halve it.
- **Expand the CVE battery.** 50+ CVEs across three languages, CVSS-banded, OWASP-aligned.
- **Per-call token instrumentation in BigQuery.** The current `benchmark_calls` schema stores latency and score but not token counts, so per-model run cost is estimated rather than measured. Adding `input_tokens`, `output_tokens`, `reasoning_tokens` columns is mechanical.
- **RouteLLM baseline.** Direct comparator on the same CVE inputs.
- **CLI wrapper.** `cacr route <prompt>` so the routing decision can be tried against real inputs outside the dashboard.

The repo is at `github.com/rjsmith87/cacr`. The dashboard is at `cacr-dashboard.onrender.com`. The whole point of empirical routing is to make the cost-vs-capability tradeoff visible enough that you can make a decision instead of a guess. If a 0.42 score is the best available for a task, the right answer is sometimes *don't ship the agent yet* — and the system needs to be able to say that out loud.
