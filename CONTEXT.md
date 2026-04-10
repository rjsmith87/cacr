# CACR — Context Briefing

## What CACR is

CACR (Cascade-Aware Confidence Routing) is a framework I built to answer: **which LLM should handle each step in a multi-step agentic pipeline to minimize cost without breaking accuracy?**

The key insight is that cascade failures are expensive. If a cheap model gets step 1 wrong, steps 2 and 3 are wasted — and you retry with an expensive model anyway. CACR accounts for this by computing expected cost inclusive of retry costs.

## The thesis

You don't need GPT-4 or Claude Sonnet for every LLM call in a pipeline. For classification tasks (bug detection, vulnerability identification), the cheapest models match the most expensive ones. The savings compound in multi-step pipelines: a 3-step pipeline with Flash Lite costs 28x less than one with Haiku, with comparable accuracy.

## Current results

- **4 models benchmarked**: Claude Haiku, Gemini 2.5 Flash, Gemini 2.5 Flash Lite, GPT-4o-mini
- **3 code-focused tasks**: CodeReview (bug type), SecurityVuln (OWASP), CodeSummarization (ROUGE-L)
- **Headline finding**: Flash Lite ($0.04/MTok) matches Haiku ($1.00/MTok) on classification and leads on summarization
- **Calibration**: GPT-4o-mini is best calibrated (knows when it's uncertain); Flash is worst (always says 10)
- **Pipeline simulation**: All-Haiku costs $0.00223 vs All-Lite at $0.00008 for similar accuracy

## Tech stack

- Python 3.13, Flask API, React + Recharts + Tailwind dashboard
- BigQuery for results storage (benchmark_calls, benchmark_summaries, pipeline_results)
- Anthropic SDK, google-genai SDK, OpenAI SDK
- scikit-learn for the CACR logistic regression router
- Render for deployment (API + static dashboard)

## Render deployment

- API: Flask + gunicorn on Render web service
- Dashboard: Vite static site on Render
- Issue: GCP ADC doesn't work on Render — needs a service account JSON or workload identity federation

## Salesforce angle

This framework directly demonstrates skills relevant to Salesforce's AI platform work:
- Multi-model routing and cost optimization
- Empirical evaluation methodology
- Production pipeline architecture
- Full-stack implementation (Python backend, React frontend, cloud infrastructure)
