"""CACR — Flask backend.

Endpoints:
  GET  /api/health           — status, model count, task count, total calls
  GET  /api/capability-matrix — models x tasks x scores heatmap data
  GET  /api/calibration       — confidence vs accuracy scatter data per model
  GET  /api/pipeline-cost     — pipeline strategy comparison
  GET  /api/cost-matrix       — cost_matrix.csv as JSON
  POST /api/route             — route a prompt to cost-optimal model
  GET  /api/findings          — FINDINGS.md as markdown
"""

import csv
import json
import os
import sys

from flask import Flask, jsonify, request, abort
from flask_cors import CORS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

app = Flask(__name__)
CORS(app)


def _load_dotenv() -> None:
    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v:
                os.environ.setdefault(k, v)


_load_dotenv()


def _bq_client():
    project = os.environ.get("GCP_PROJECT")
    if not project:
        abort(500, "GCP_PROJECT not set")
    from google.cloud import bigquery
    return bigquery.Client(project=project)


# ── GET /api/health ────────────────────────────────────────────────

@app.route("/api/health")
def health():
    try:
        client = _bq_client()
        row = list(client.query(
            "SELECT COUNT(*) as n FROM `cacr_results.benchmark_calls`"
        ).result())[0]
        total_calls = row.n

        models = list(client.query(
            "SELECT COUNT(DISTINCT model) as n FROM `cacr_results.benchmark_summaries`"
        ).result())[0].n

        tasks = list(client.query(
            "SELECT COUNT(DISTINCT task) as n FROM `cacr_results.benchmark_summaries`"
        ).result())[0].n
    except Exception:
        total_calls, models, tasks = 0, 0, 0

    return jsonify({
        "status": "ok",
        "model_count": models,
        "task_count": tasks,
        "total_benchmark_calls": total_calls,
    })


# ── GET /api/capability-matrix ─────────────────────────────────────

@app.route("/api/capability-matrix")
def capability_matrix():
    client = _bq_client()
    rows = list(client.query("""
        SELECT task, model, tier, mean_score, mean_confidence,
               calibration_r, mean_latency_ms, passes_threshold
        FROM `cacr_results.benchmark_summaries`
        WHERE run_ts = (SELECT MAX(run_ts) FROM `cacr_results.benchmark_summaries`)
        ORDER BY task, model
    """).result())
    return jsonify([dict(r) for r in rows])


# ── GET /api/calibration ───────────────────────────────────────────

@app.route("/api/calibration")
def calibration():
    client = _bq_client()
    rows = list(client.query("""
        SELECT model, task, difficulty, score, confidence_score
        FROM `cacr_results.benchmark_calls`
        WHERE run_ts = (SELECT MAX(run_ts) FROM `cacr_results.benchmark_calls`)
          AND confidence_score IS NOT NULL
        ORDER BY model, task
    """).result())
    return jsonify([dict(r) for r in rows])


# ── GET /api/pipeline-cost ─────────────────────────────────────────

@app.route("/api/pipeline-cost")
def pipeline_cost():
    client = _bq_client()
    try:
        rows = list(client.query("""
            SELECT *
            FROM `cacr_results.pipeline_results`
            WHERE event = 'pipeline_summary'
            ORDER BY strategy
        """).result())
        return jsonify([dict(r) for r in rows])
    except Exception:
        return jsonify([])


# ── GET /api/cost-matrix ───────────────────────────────────────────

@app.route("/api/cost-matrix")
def cost_matrix():
    csv_path = os.path.join(_ROOT, "results", "cost_matrix.csv")
    if not os.path.exists(csv_path):
        abort(404, "cost_matrix.csv not found. Run router/cost_model.py first.")
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            for k in ["mean_score", "expected_cost_usd", "score_cost_ratio",
                       "cost_per_token", "mean_latency_ms", "calibration_r"]:
                if k in row and row[k]:
                    try:
                        row[k] = float(row[k])
                    except ValueError:
                        pass
            for k in ["passes_threshold", "is_cost_optimal"]:
                if k in row:
                    row[k] = row[k].lower() == "true"
            rows.append(row)
    return jsonify(rows)


# ── POST /api/route ────────────────────────────────────────────────

@app.route("/api/route", methods=["POST"])
def route_prompt():
    data = request.get_json(force=True)
    if not data or "prompt" not in data:
        abort(400, "Missing 'prompt' in request body")

    from router.policy import CACRRouter

    router = CACRRouter()
    router.load()
    decision = router.route(
        data["prompt"],
        task_family=data.get("task_family", "classification"),
        complexity=data.get("complexity", "medium"),
        pipeline_position=data.get("pipeline_position", 1),
        upstream_confidence=data.get("upstream_confidence", 0.8),
    )
    return jsonify({
        "recommended_model": decision.recommended_model,
        "expected_cost": decision.expected_cost,
        "confidence_interval": list(decision.confidence_interval),
        "reasoning": decision.reasoning,
    })


# ── GET /api/findings ──────────────────────────────────────────────

@app.route("/api/findings")
def findings():
    path = os.path.join(_ROOT, "FINDINGS.md")
    if not os.path.exists(path):
        abort(404, "FINDINGS.md not found")
    with open(path) as f:
        return jsonify({"content": f.read()})


if __name__ == "__main__":
    app.run(debug=True, port=8000)
