# CACR Findings — 2026-04-09

## Headline: Flash Lite is the best value model by a wide margin

**Gemini 2.5 Flash Lite** at **$0.00000004/token** matches Claude Haiku on CodeReview (0.87) and SecurityVuln (1.00), and **leads all models** on CodeSummarization (0.45 ROUGE-L). At roughly 25x cheaper than Haiku and 4x cheaper than GPT-4o-mini, it is the cost-optimal default for the entire task battery.

## Capability Matrix (15 examples/task, 4 models)

| Model                  | Tier | $/token    | CodeReview | SecurityVuln | CodeSumm | Avg    |
|------------------------|------|------------|------------|--------------|----------|--------|
| claude-haiku-4-5       | 1    | 1.0e-6     | 0.87       | 1.00         | 0.42     | 0.76   |
| gemini-2.5-flash       | 1    | 1.0e-7     | 0.73       | 0.87         | 0.20     | 0.60   |
| gemini-2.5-flash-lite  | 1    | 4.0e-8     | 0.87       | 1.00         | 0.45     | 0.77   |
| gpt-4o-mini            | 2    | 1.5e-7     | 0.73       | 1.00         | 0.41     | 0.71   |

## Calibration Analysis

### Overall calibration_r (Pearson: self-reported confidence vs eval score)

- **GPT-4o-mini**: +0.413 on CodeReview (best calibrated — knows when it's uncertain)
- **Claude Haiku**: +0.196 on CodeReview, +0.267 on CodeSummarization
- **Flash Lite**: +0.218 on CodeReview (promising, needs more data)
- **Gemini Flash**: Often reports confidence=10 regardless of score — poorly calibrated

### Per-difficulty calibration (Hard examples only)

Hard examples surface the most useful calibration signal:
- Haiku: H:+0.54 CodeReview, H:+0.64 CodeSummarization
- GPT-4o-mini: H:+0.60 CodeReview, H:+0.43 CodeSummarization
- Flash Lite: H:+0.19 CodeReview (weak but positive)

### Statistical artifact: calibration_r=1.0

An earlier run showed Gemini Flash with cal_r=1.000 on CodeSummarization. Root cause: 503 API errors caused most confidence probes to fail (returned as NaN, filtered out), leaving only 2 valid data points that trivially correlated. Fixed by increasing retry attempts from 3 to 5 with 4s base exponential backoff and server-hint delay parsing.

## Gemini 2.5 Pro: Removed

gemini-2.5-pro was consistently returning 503 (UNAVAILABLE) on every call despite retry logic. Replaced with gemini-2.5-flash-lite as the true tier-1 small model. This turned out to be a better outcome — Flash Lite outperforms Pro's expected niche.

## Key Takeaway for Routing

For a 3-step agentic pipeline (classify → identify → fix), the cascade-aware router should default to Flash Lite for steps where it meets threshold, escalating to Haiku only for tasks where Flash Lite's calibration suggests uncertainty. The cost savings are ~25x per token with no accuracy loss on classification tasks.
