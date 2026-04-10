# CACR Methodology — Cascade-Aware Confidence Routing

## Why cascade failure costs matter

Modern agentic pipelines chain multiple LLM calls in sequence: a code review agent might first classify bug severity, then identify the bug type, then generate a fix. When a cheap model makes an error at step 1, that error propagates downstream — step 3 generates a fix for the wrong bug type. The pipeline must then retry, typically with a more expensive model.

Traditional model routing optimizes per-call cost: pick the cheapest model that meets an accuracy threshold. This ignores the multiplicative cost of cascade failures. A model that saves $0.001 per call but fails 20% more often costs far more in a 3-step pipeline, because each failure triggers an expensive retry across all downstream steps.

CACR accounts for this by computing expected cost inclusive of cascade failure retries:

```
expected_cost = (model_cost × tokens) × P(success) + (retry_cost) × P(failure) × cascade_depth
```

Where `retry_cost` is the cost of falling back to a reliable model (Haiku in our case) and `cascade_depth` is the pipeline length.

## Task battery design

We evaluate models on three code-focused tasks chosen to span the classification-generation spectrum:

**CodeReview** (30 examples, classification): Given a Python snippet with a known bug, identify the bug type from 5 categories: logic_error, null_pointer, off_by_one, resource_leak, race_condition. Scored by exact match. Examples range from obvious single-line bugs (easy) to obfuscated multi-function reasoning (hard).

**SecurityVuln** (30 examples, classification): Given a code snippet, identify the vulnerability type from 5 OWASP-aligned categories: sql_injection, xss, path_traversal, hardcoded_secret, insecure_deserialization. Scored by exact match. Hard examples include second-order SQL injection, YAML deserialization, and path traversal hidden behind insufficient sanitization.

**CodeSummarization** (30 examples, generation): Given a Python function, produce a one-sentence summary. Scored using ROUGE-L F1 against a reference summary. Hard examples use obfuscated variable names (single letters, abbreviations) and require understanding algorithms like CRC-32, dynamic time warping, and ring buffers.

Each task has a 10/10/10 split across easy/medium/hard difficulty levels. Hard examples are specifically designed to require multi-line reasoning, not just pattern matching — this is where model differences become most apparent.

## Confidence calibration measurement

After each model call, we make a second call asking the model to rate its confidence from 1-10. We then compute the Pearson correlation coefficient between self-reported confidence scores and actual eval scores across all examples in a (task, model) pair.

We chose Pearson r because:
1. It captures linear correlation between confidence and accuracy — a well-calibrated model should show positive r (higher confidence on correct answers)
2. It's invariant to the scale of confidence scores — a model that always says 7-9 can still be well-calibrated if 9s are more accurate than 7s
3. It's undefined when variance is zero, which correctly flags degenerate cases (a model that always says 10)

Calibration is computed overall and per-difficulty level. The per-difficulty breakdown is the more actionable signal: a model that is well-calibrated on hard examples (H:+0.60) is a better routing candidate than one that is uncalibrated (H:N/A), because the router can use the confidence score to decide when to escalate.

### Limitations of the calibration metric

- Small sample sizes (10 examples per difficulty) make Pearson r noisy. We observed a cal_r=1.000 artifact from 503 dropouts leaving only 2 valid data points.
- Self-reported confidence is a proxy, not a probability. Models trained with RLHF may be systematically overconfident.
- The confidence probe adds latency and cost (doubles the API calls). In production, you'd use logprob-based confidence instead.

## Results

### Capability scores (30 examples/task)

| Model                  | CodeReview | SecurityVuln | CodeSumm | Mean |
|------------------------|------------|--------------|----------|------|
| claude-haiku-4-5       | 0.90       | 1.00         | 0.38     | 0.76 |
| gemini-2.5-flash       | 0.83       | 0.90         | 0.34     | 0.69 |
| gemini-2.5-flash-lite  | 0.90       | 0.93         | 0.42     | 0.75 |
| gpt-4o-mini            | 0.77       | 0.93         | 0.40     | 0.70 |

Flash Lite ($0.04/MTok) matches Haiku ($1.00/MTok) on CodeReview and nearly matches on SecurityVuln, while leading on CodeSummarization. This makes it the cost-optimal choice on all three tasks.

### Calibration highlights

- GPT-4o-mini shows the strongest calibration: +0.251 overall on CodeReview, +0.663 on SecurityVuln, and H:+0.82 on hard CodeReview examples
- Claude Haiku is moderately calibrated: +0.189 on CodeSummarization
- Gemini Flash is poorly calibrated — frequently reports confidence=10 regardless of score
- Flash Lite shows weak positive calibration on CodeReview (+0.218), needs more data

### Pipeline simulation

A 3-step pipeline (severity → bug type → fix) run on 10 code snippets:

| Strategy    | Step1 Acc | Step2 Acc | Step3 Acc | Cascade Fail | Cost        | Latency |
|-------------|-----------|-----------|-----------|--------------|-------------|---------|
| all-haiku   | 0.30      | 0.80      | 0.20      | 0.80         | $0.00223    | 2183ms  |
| all-lite    | 0.20      | 1.00      | 0.20      | 0.80         | $0.00008    | 1319ms  |
| cacr-routed | 0.20      | 1.00      | 0.20      | 0.80         | $0.00008    | 1456ms  |

Step 1 (severity classification) is the weak link across all strategies — the severity categories (critical/high/medium/low) are subjective and models disagree with the gold labels. Step 2 (bug type) is strong. The cost difference is dramatic: Haiku costs 28x more for similar accuracy.

## Future work

1. **Logprob-based confidence**: Replace the second API call with native logprob extraction, halving latency and cost
2. **Larger task battery**: Expand to 100+ examples per task for statistically significant calibration measurements
3. **More models**: Add Claude Sonnet, GPT-4o, Gemini Pro to establish the full cost-quality frontier
4. **Dynamic routing**: Train the router to use upstream confidence as a signal — if step 1's confidence is low, escalate step 2 to a more expensive model
5. **Production pipeline integration**: Wire CACR into a real code review agent and measure end-to-end savings
