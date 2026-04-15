# CVE Security Case Study — Pre-Registration

**Registered:** 2026-04-14
**Status:** Pre-registered before data collection. This document is frozen once
commit #1 lands; any later revision requires a dated amendment below.

The purpose of this document is to lock in success and failure criteria
**before** running the CVE battery so that results cannot be reshaped after
the fact to favor CACR. We are doing research, not marketing.

---

## 1. Hypothesis

On security tasks, *confidently wrong* answers from cheap models impose a
cascade cost that outweighs their per-token savings. A router that conditions
on empirical per-task calibration (CACR) will produce fewer dangerous
high-confidence errors than a router that conditions on learned
accuracy-difficulty signals (RouteLLM), at matched or lower spend.

If this hypothesis is false, we will say so.

## 2. Battery

- **n = 15** CVEs: 5 Python, 5 Java, 5 JavaScript
- **Severity distribution:** 5 critical, 6 high, 4 medium (CVSS v3.1 NVD bands)
- **Taxonomy of `vuln_class`:** Injection, Deserialization, Prototype Pollution,
  Authentication Bypass, Information Disclosure, SSRF, Path Traversal,
  Cryptographic Failure, ReDoS, Other
- **Gold severity label:** NVD CVSS v3.1 base-score band (not our opinion).
  Where NVD and vendor disagree, NVD is canonical and the disagreement is
  footnoted in the CVE record.
- **Snippets:** 15–40 LOC of the actual pre-patch code from the public
  advisory or CVE record. No synthesized vulnerabilities unless clearly
  labeled "adversarial subset."

## 3. Primary metric — `dangerous_rate`

For each (model, CVE) call, scored over the full 15-case battery:

```
correct_i        = 1 if vuln_class matches gold AND severity matches gold else 0
dangerous_i      = 1 if correct_i == 0 AND confidence_i >= 8 else 0
dangerous_rate   = mean(dangerous_i) over i = 1..N
```

This is the headline. A model that is less accurate but never confidently
wrong is safer than a model that is more accurate but occasionally
confidently wrong.

## 4. Secondary metrics

- `accuracy = mean(correct_i)`
- `overconfidence = mean((confidence_i / 10) * (1 - correct_i))`
- `ECE` (Expected Calibration Error, 10 equal-width bins on confidence/10)
- `silent_miss_rate` — severity underestimated by ≥1 tier AND confidence ≥ 7
- Expected pipeline cost including cascade penalty (see §6)

## 5. Calibration failure — precise definition

A call is a **dangerous failure** iff:
1. `vuln_class_predicted ≠ vuln_class_gold` OR `severity_predicted ≠ severity_gold`, AND
2. `confidence_predicted ≥ 8` (on the 0–10 self-report scale)

The confidence threshold of 8 is chosen before data collection. We will
additionally report the full curve `dangerous_rate(τ)` for τ ∈ {5, 6, 7, 8, 9, 10}
for transparency, but the headline number uses τ = 8.

## 6. Cascade cost model

Three-step security pipeline: (1) triage severity, (2) identify vuln class
and generate fix, (3) write regression test.

Token budgets (fixed across models to isolate price, not verbosity):

| Step | Input tokens | Output tokens |
|------|--------------|---------------|
| 1 triage        | 400   | 80  |
| 2 fix generation| 1,200 | 600 |
| 3 regression test| 900  | 400 |

Prices (per 1M tokens, list prices as of April 2026, versioned in
`pricing.py` with date stamp):

| Model                  | $/M input | $/M output |
|------------------------|-----------|------------|
| Gemini 2.5 Flash Lite  | 0.10      | 0.40       |
| Gemini 2.5 Flash       | 0.30      | 2.50       |
| Claude Haiku           | 0.80      | 4.00       |
| GPT-4o-mini            | 0.15      | 0.60       |
| Claude Sonnet (escalation tier) | 3.00 | 15.00 |

**Expected cost per pipeline call:**

```
E[cost | model m, task_family t] =
    cost_happy_path(m) + dangerous_rate(m, t) * cost_cascade_penalty
```

where `cost_cascade_penalty` is the cost of re-running steps 2 and 3 on
Claude Sonnet after a downstream validator catches the miss (~$0.0237 by
the math in the spec).

## 7. CACR routing rule (pre-registered)

```
for each candidate model m in choice_set:
    E_cost[m] = list_cost(m) + dangerous_rate(m, task_family) * cascade_penalty
pick argmin E_cost[m]
```

`dangerous_rate(m, task_family)` is the **empirical** value from this very
CVE battery. We disclose this up front: the router is fit to the data it
will be judged on. To control for overfitting we will report k-fold (k=5)
cross-validated routing decisions in addition to the in-sample number, and
use the CV number for the RouteLLM comparison.

## 8. RouteLLM baseline

- Library: `routellm` (pip), published `mf_gpt4_augmented` checkpoint
- Strong model: Claude Sonnet
- Weak model: Gemini Flash Lite
- Thresholds: α ∈ {0.2, 0.5, 0.8}
- CACR is given the same binary choice set for apples-to-apples; a
  four-model variant is reported as an ablation only.

**Known caveat:** RouteLLM checkpoints were trained on GPT-4 vs Mixtral
pairs. Using them to route Sonnet vs Flash Lite is slightly off-distribution
and will be disclosed in the write-up.

## 9. Success criteria (win conditions)

CACR wins if **all three** hold at matched or lower expected spend:

1. `accuracy(CACR) ≥ accuracy(RouteLLM) - ε`, where ε = 0.05 (one CVE on n=15)
2. `dangerous_rate(CACR) ≤ dangerous_rate(RouteLLM) - 0.10` (absolute)
3. `E[cost](CACR) ≤ 0.80 * E[cost](RouteLLM)` on the security task family

Headline framing if won:
> *RouteLLM routes for accuracy. CACR routes for calibration. On security
> tasks, calibration wins.*

## 10. Failure criteria (what an honest loss looks like)

We report a null or negative result if **any** of the following hold. We
will publish the result unchanged.

- **Null result:** all four models exhibit `dangerous_rate ≤ 0.05` on the
  battery. Calibration does not discriminate; router has nothing to do.
  This falsifies the thesis on this battery.
- **RouteLLM matches or beats CACR on `dangerous_rate`:** their learned
  difficulty signal is already capturing what we thought was uniquely
  calibration-driven. We will publish and investigate why.
- **Trade-off loss:** CACR wins on `dangerous_rate` but loses ≥ 0.10
  absolute accuracy. We report the trade-off curve. We do not cherry-pick
  the axis where we win.
- **Flash-vs-Flash-Lite smoke test shows gap has closed:** if the prior
  6/12 vs 12/12 divergence is gone when re-run on current model versions,
  the CVE battery will not discriminate models and the study pivots or
  expands. Smoke test runs as commit #2 before the full battery is built.

## 11. Statistical caveats

- n=15 yields a 95% Wilson CI of roughly ±0.25 on `dangerous_rate` at
  p=0.2. Differences of 0.10 between routers **will not clear statistical
  significance.** We can show direction and mechanism; we will not claim
  a significant effect without expanding to ~50.
- Confidence intervals: Wilson for accuracy and dangerous_rate, 1,000-sample
  bootstrap for ECE and expected cost.
- All per-model, per-CVE raw results are committed to the repo as JSONL
  so any reviewer can recompute.

## 12. What we will not do

- We will not re-run the battery after seeing results and report only the
  favorable run.
- We will not change the confidence threshold τ = 8 after seeing results.
- We will not swap CVEs out of the battery after running to improve
  headline numbers.
- We will not change the choice set for CACR vs RouteLLM after running.
- We will not present in-sample CACR routing numbers as the headline; the
  5-fold CV number is the headline.

## 13. Amendment log

*(Amendments must be dated and signed. The frozen text above does not
change; amendments are appended here.)*

(none)
