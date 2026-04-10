# Overnight Run Issues Log — 2026-04-09/10

## Completed
- [x] FINDINGS.md + initial commit
- [x] Expand task battery to 30 examples each (10/10/10 easy/medium/hard)
- [x] Re-run benchmark + BQ write (372 rows)
- [x] Pipeline simulation (33 rows to BQ)
- [x] Cascade cost model (cost_matrix.csv generated)
- [x] Router (LookupTableRouter + CACRRouter trained)
- [x] Flask API (7 endpoints)
- [x] React dashboard (5 views)
- [x] Render deployment config (render.yaml + sync script)
- [x] Makefile (8 targets)
- [x] Documentation (README, METHODOLOGY, CLAUDE.md, CONTEXT.md, CHANGELOG, FINDINGS)
- [x] Final commit + push

## Issues Encountered

### 1. Gemini 503 rate limiting (recurring)
**Severity**: Medium — mitigated but not eliminated
**Details**: gemini-2.5-flash hits 503 UNAVAILABLE under sustained load. 5-retry with 4s base backoff handles most cases but occasional calls still fail after all retries.
**Impact**: Benchmark scores for Gemini models may be slightly lower than true capability due to 503s scoring as 0.
**Mitigation**: Retry logic with server-hint delay parsing. Consider adding per-model rate limiting (e.g., 1s delay between calls to same model).

### 2. Pipeline step 1 accuracy is low across all models (0.20-0.30)
**Severity**: Low — task design issue, not a framework bug
**Details**: The severity classification step (critical/high/medium/low) has subjective gold labels. Models frequently disagree on whether a divide-by-zero is "critical" vs "high".
**Fix**: Revise gold labels to match model consensus, or switch to a binary severity scale (high/low).

### 3. CACR router is trivial (always picks Flash Lite)
**Severity**: Low — correct behavior given current data
**Details**: Flash Lite is cost-optimal on all 3 tasks, so the logistic regression just predicts Flash Lite regardless of features.
**Fix**: Add tasks or models where Flash Lite fails threshold to create meaningful routing decisions.

### 4. Render deployment: GCP ADC won't work
**Severity**: Medium — blocks production deployment
**Details**: The Flask API uses BigQuery via ADC (application default credentials). On Render, there's no `gcloud auth` — need a service account JSON. But the GCP org policy (`constraints/iam.disableServiceAccountKeyCreation`) blocks SA key creation.
**Proposed solutions**:
  1. Ask GCP org admin to create an exception for the CACR service account
  2. Use Workload Identity Federation with Render's OIDC provider
  3. Export BQ data to a static JSON file served by the API (no live BQ queries)
  4. Switch to a GCP-hosted backend (Cloud Run) where ADC works natively

### 5. Calibration metric has high variance at 10 examples/difficulty
**Severity**: Low — expected with small samples
**Details**: Pearson r with n=10 is noisy. Some per-difficulty cal_r values flip sign between runs.
**Fix**: Expand to 30+ examples per difficulty level (90 total per task).
