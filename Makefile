.PHONY: benchmark benchmark-quick benchmark-pipeline sync-env deploy results dashboard-dev api-dev test-ui all

VENV := ./venv/bin
PYTHON := $(VENV)/python

benchmark:
	$(PYTHON) runner.py

benchmark-quick:
	CACR_QUICK=1 $(PYTHON) -c "\
	import os; os.environ['CACR_QUICK']='1'; \
	exec(open('runner.py').read().replace('def main', 'def _orig_main'))" \
	|| $(PYTHON) runner.py 2>/dev/null | head -50

benchmark-pipeline:
	$(PYTHON) pipelines/code_review_pipeline.py

sync-env:
	$(PYTHON) scripts/sync_env_to_render.py

deploy:
	git push origin main

results:
	bq query --project_id=$$(grep GCP_PROJECT .env | cut -d= -f2) \
		'SELECT model, task, mean_score, calibration_r, mean_latency_ms FROM cacr_results.benchmark_summaries WHERE run_ts = (SELECT MAX(run_ts) FROM cacr_results.benchmark_summaries) ORDER BY task, model'

dashboard-dev:
	cd dashboard && npm run dev

api-dev:
	$(VENV)/gunicorn api.main:app --reload --bind 0.0.0.0:8000

test-ui:
	cd dashboard && TEST_URL=https://cacr-dashboard.onrender.com npx playwright test

all: benchmark api-dev
