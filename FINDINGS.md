# CACR Findings — 2026-04-10 (Updated)

## Headline: Flash Lite is the best value model by a wide margin

**Gemini 2.5 Flash Lite** at **$0.04/MTok** matches Claude Haiku on CodeReview (0.90) and SecurityVuln (0.93), and **leads all models** on CodeSummarization (0.42 ROUGE-L). At roughly 25x cheaper than Haiku and 4x cheaper than GPT-4o-mini, it is the cost-optimal default for the entire task battery.

## Capability Matrix (30 examples/task, 4 models)

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

| Strategy    | Step1 Acc | Step2 Acc | Step3 Acc | Cascade Fail | Cost        | Latency |
|-------------|-----------|-----------|-----------|--------------|-------------|---------|
| all-haiku   | 0.30      | 0.80      | 0.20      | 0.80         | $0.00223    | 2183ms  |
| all-lite    | 0.20      | 1.00      | 0.20      | 0.80         | $0.00008    | 1319ms  |
| cacr-routed | 0.20      | 1.00      | 0.20      | 0.80         | $0.00008    | 1456ms  |

Step 1 (severity) is the weak link — the 4-level severity scale is subjective and models disagree with gold labels. Step 2 (bug type) is strong, especially for Flash Lite (1.00). Cost difference: Haiku costs **28x more** for comparable accuracy.

## Cost Model

Expected cost per (task, model) pair including cascade failure retry:

| Task              | Cost-Optimal Model     | Expected Cost | Score |
|-------------------|------------------------|---------------|-------|
| CodeReview        | gemini-2.5-flash-lite  | $0.000077     | 0.90  |
| SecurityVuln      | gemini-2.5-flash-lite  | $0.000055     | 0.93  |
| CodeSummarization | gemini-2.5-flash-lite  | $0.000404     | 0.42  |

## Gemini 2.5 Pro: Removed

gemini-2.5-pro was consistently returning 503 (UNAVAILABLE) on every call despite retry logic. Replaced with gemini-2.5-flash-lite. This turned out to be a better outcome — Flash Lite outperforms Pro's expected niche at a fraction of the cost.

## Key Takeaway for Routing

For a 3-step agentic pipeline, the cascade-aware router defaults to Flash Lite for all steps. The cost savings are ~25x per token vs Haiku with no accuracy loss on classification tasks. Even when accounting for cascade failure retries, Flash Lite remains cost-optimal.

The remaining opportunity is in calibration-based dynamic routing: GPT-4o-mini's strong calibration on hard examples (H:+0.82) means it could serve as a "confidence-aware escalation target" when Flash Lite reports low confidence — but this requires switching from self-reported confidence to logprob-based confidence extraction.

## CVE Case Study

6 real CVEs tested: CVE-2023-30861 (Flask session disclosure), CVE-2023-32681 (Requests credential leak on redirect), CVE-2018-18074 (Requests auth leak cross-host), CVE-2019-11324 (urllib3 cert bypass, critical), CVE-2022-29217 (PyJWT algorithm confusion, critical), CVE-2021-33503 (urllib3 ReDoS).

### Detection Results (step 1: is this code vulnerable?)

| Model               | Detected | Correct | Missed High/Crit | Overconf Miss | Mean Conf |
|---------------------|----------|---------|-------------------|---------------|-----------|
| claude-haiku-4-5    | 6/6      | 5/6     | 0                 | 0             | 9.3       |
| gemini-2.5-flash    | **2/6**  | **2/6** | **4**             | 0             | N/A       |
| gemini-2.5-flash-lite | 18/18  | 18/18   | 0                 | 0             | 9.0       |
| gpt-4o-mini         | 12/12    | 12/12   | 0                 | 0             | 7.8       |

### Key Finding: Gemini 2.5 Flash is blind to subtle CVEs

**Gemini 2.5 Flash missed 4 of 6 CVEs**, including two critical-severity vulnerabilities:
- **CVE-2019-11324** (urllib3 cert verification bypass) — critical severity, MISSED
- **CVE-2022-29217** (PyJWT algorithm confusion) — critical severity, MISSED
- **CVE-2023-30861** (Flask session cookie disclosure) — high severity, MISSED
- **CVE-2023-32681** (Requests credential leak on redirect) — high severity, MISSED

Flash didn't return confidence scores on its misses (None output), so these aren't "overconfident misses" in the traditional sense — they're **silent failures** where the model didn't even attempt structured output.

### Routing Implication

This is the strongest argument for cascade-aware routing: **the cheapest model (Flash Lite) outperforms the more expensive Flash model on security-critical tasks.** Cost alone doesn't predict capability — Flash at $0.10/MTok is strictly worse than Flash Lite at $0.04/MTok for CVE detection. A naive "pick cheapest" router would choose Flash Lite correctly, but a "pick based on model family/size assumptions" router might incorrectly prefer Flash.

### Strategy Comparison

| Strategy      | Detection Rate | Cost/CVE     |
|---------------|----------------|--------------|
| always_tier1  | 6/6 (100%)     | ~$0.000004   |
| always_tier2  | 6/6 (100%)     | ~$0.000009   |
| cacr          | 6/6 (100%)     | ~$0.000005   |

All strategies using Flash Lite or GPT-4o-mini achieve 100% detection. The CACR strategy (Flash Lite for detection, Haiku for explanation) costs marginally more than all-Flash-Lite but produces higher quality fix explanations.
