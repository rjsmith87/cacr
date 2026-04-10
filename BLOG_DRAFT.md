# The $0.00000004 Security Scanner: How the Cheapest Model Beat Its Expensive Sibling on Real CVEs

We tested four LLMs on 12 real CVEs. The cheapest model detected all 12. The model that costs 2.5x more missed half of them — silently.

## The setup

CACR (Cascade-Aware Confidence Routing) is a framework for finding the cheapest LLM that won't break a multi-step pipeline. Instead of assuming bigger models are better, it benchmarks every model on every task and picks the cheapest one that passes an accuracy threshold — while accounting for the compounding cost of failures in chained pipelines.

We built a 2-step security scanning pipeline: step 1 detects whether code is vulnerable (yes/no + severity + confidence 1-10), step 2 explains the attack vector and suggests a fix. We ran it against 12 real, patched CVEs in popular Python libraries: Flask, Requests, urllib3, Jinja2, PyJWT, PyYAML, Werkzeug, and certifi. Severity distribution: 3 critical, 5 high, 4 medium.

## The models

| Model                  | Price ($/MTok) | Tier |
|------------------------|----------------|------|
| claude-haiku-4-5       | $1.00          | 1    |
| gemini-2.5-flash       | $0.10          | 1    |
| gemini-2.5-flash-lite  | $0.04          | 1    |
| gpt-4o-mini            | $0.15          | 2    |

## The results

| Model               | CVEs Detected | Missed High/Crit | Mean Confidence |
|---------------------|---------------|-------------------|-----------------|
| claude-haiku-4-5    | 12/12         | 0                 | 9.0             |
| gemini-2.5-flash    | **6/12**      | **2**             | N/A             |
| gemini-2.5-flash-lite | 12/12       | 0                 | 9.3             |
| gpt-4o-mini         | 12/12         | 0                 | 8.0             |

Three models detected all 12 CVEs. Gemini 2.5 Flash missed six.

## What Flash missed

The CVEs that Flash failed to detect:

- **CVE-2018-18074** — Requests leaks HTTP Basic Auth credentials on cross-host redirects. High severity.
- **CVE-2023-25577** — Werkzeug multipart parser consumes excessive memory on crafted requests. High severity.
- **CVE-2021-33503** — urllib3 ReDoS via URL authority parsing.
- **CVE-2020-28493** — Jinja2 ReDoS via urlize filter.
- **CVE-2022-23491** — certifi shipped with a compromised root CA (TrustCor).
- **CVE-2020-26137** — urllib3 CRLF injection in HTTP headers.

These aren't obscure edge cases. They're real vulnerabilities in libraries with hundreds of millions of downloads. And Flash didn't just get them wrong — it returned no parseable output at all. No confidence score, no severity guess. Silent failures with no signal for retry or escalation.

The CVEs Flash did detect (CVE-2023-30861, CVE-2023-32681, CVE-2019-11324, CVE-2022-29217, CVE-2021-28363, CVE-2019-20477) tend to be the most "textbook" patterns — the kind that show up in security training materials. The library-level, design-flaw vulnerabilities are where it falls apart.

## The $0.04/MTok model detected everything

Flash Lite, at $0.04/MTok, detected all 12 CVEs with a mean confidence of 9.3. It costs 2.5x less than Flash. It costs 25x less than Haiku. And it didn't miss a single one.

This isn't just about the CVE case study. On the broader CACR benchmark battery (30 examples each across CodeReview, SecurityVuln, and CodeSummarization), Flash Lite matched Haiku on code review accuracy (0.90 vs 0.90), nearly matched on security vulnerability detection (0.93 vs 1.00), and led on code summarization (0.42 vs 0.38 ROUGE-L).

## Why this matters for pipelines

In an agentic pipeline, a wrong answer at step 1 propagates. If your security scanner says "not vulnerable" on a critical CVE, step 2 (explain the fix) never runs. The user sees a clean report. The vulnerability ships.

The cascade cost formula:

```
expected_cost = (model_cost × tokens) × P(success) + (retry_cost) × P(failure) × cascade_depth
```

For a 2-step security pipeline with Flash (50% detection rate on CVEs):
- P(failure) = 0.50
- retry_cost = cost of a Haiku call as fallback = ~$0.00023
- cascade_depth = 2
- expected_cost = (0.10/MTok × 200 tokens × 0.50) + ($0.00023 × 0.50 × 2) = **$0.00024/scan**

For the same pipeline with Flash Lite (100% detection rate):
- P(failure) ≈ 0
- expected_cost = 0.04/MTok × 200 tokens × 1.0 = **$0.000008/scan**

Flash Lite is **30x cheaper per scan** when you account for cascade failures. And it doesn't miss critical vulnerabilities.

## The takeaway

Don't pick models by name, family, or price tier. Pick them by measured performance on your actual task. The model that costs $0.00000004 per token outperformed the one that costs $0.0000001 per token — not by a little, but by detecting twice as many security vulnerabilities.

If you're building a pipeline that chains LLM calls, benchmark every step empirically. The savings compound.

---

*[Live dashboard](https://cacr-dashboard.onrender.com) | [GitHub](https://github.com/rjsmith87/cacr)*
