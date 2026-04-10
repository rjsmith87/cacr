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
    # Use the same credential strategy as bq_writer.py:
    # GOOGLE_APPLICATION_CREDENTIALS_JSON (Render) → ADC (local)
    from results.bq_writer import _build_bq_client
    return _build_bq_client(project)


# ── GET /health (Render health check) ──────────────────────────────

@app.route("/health")
def health_check():
    return {"status": "ok"}


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
    try:
        client = _bq_client()
        rows = list(client.query("""
            SELECT task, model, tier, mean_score, mean_confidence,
                   calibration_r, mean_latency_ms, passes_threshold
            FROM `cacr_results.benchmark_summaries`
            WHERE run_ts = (SELECT MAX(run_ts) FROM `cacr_results.benchmark_summaries`)
            ORDER BY task, model
        """).result())
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# ── GET /api/calibration ───────────────────────────────────────────

@app.route("/api/calibration")
def calibration():
    try:
        client = _bq_client()
        rows = list(client.query("""
            SELECT model, task, difficulty, score, confidence_score
            FROM `cacr_results.benchmark_calls`
            WHERE run_ts = (SELECT MAX(run_ts) FROM `cacr_results.benchmark_calls`)
              AND confidence_score IS NOT NULL
            ORDER BY model, task
        """).result())
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


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

    from router.complexity import infer_complexity
    from router.policy import LookupTableRouter

    # Infer complexity if "auto" or missing
    complexity = data.get("complexity", "auto")
    inferred = None
    if complexity == "auto" or not complexity:
        inferred = infer_complexity(data["prompt"])
        complexity = inferred

    router = LookupTableRouter()
    task = data.get("task", "CodeReview")
    decision = router.route(task)

    resp = {
        "recommended_model": decision.recommended_model,
        "expected_cost": decision.expected_cost,
        "confidence_interval": list(decision.confidence_interval),
        "reasoning": decision.reasoning,
        "complexity": complexity,
    }
    if inferred:
        resp["inferred_complexity"] = inferred
    return jsonify(resp)


# ── GET /api/findings ──────────────────────────────────────────────

@app.route("/api/findings")
def findings():
    path = os.path.join(_ROOT, "FINDINGS.md")
    if not os.path.exists(path):
        abort(404, "FINDINGS.md not found")
    with open(path) as f:
        return jsonify({"content": f.read()})


# ── POST /api/explain-calibration ──────────────────────────────────

@app.route("/api/explain-calibration", methods=["POST"])
def explain_calibration():
    """Send calibration data to Claude for a plain-English explanation."""
    data = request.get_json(force=True)
    cal_data = data.get("calibration_data")
    if not cal_data:
        abort(400, "Missing 'calibration_data' in request body")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    from anthropic import Anthropic

    # Summarize the raw data so the prompt isn't huge
    by_model = {}
    for row in cal_data:
        m = row.get("model", "unknown")
        by_model.setdefault(m, []).append(row)

    summary_lines = []
    for model, rows in by_model.items():
        confs = [r["confidence_score"] for r in rows if r.get("confidence_score") is not None]
        scores = [r["score"] for r in rows if r.get("score") is not None]
        n = len(rows)
        mean_conf = sum(confs) / len(confs) if confs else 0
        mean_score = sum(scores) / len(scores) if scores else 0
        summary_lines.append(
            f"{model}: {n} data points, mean confidence={mean_conf:.1f}/10, "
            f"mean accuracy={mean_score:.3f}"
        )
    summary = "\n".join(summary_lines)

    prompt = (
        "You are explaining a calibration scatter plot to a non-technical engineer. "
        f"Here is the calibration data:\n\n{summary}\n\n"
        "In 3-4 sentences, explain what this chart shows, which model is best "
        "calibrated, which is worst, and what that means in plain English for "
        "someone running an AI pipeline in production. Be direct and specific — "
        "use the actual model names and numbers."
    )

    try:
        client = Anthropic(api_key=api_key)
        # Stream the response
        text_parts = []
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                text_parts.append(text)

        return jsonify({"explanation": "".join(text_parts)})
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# ── POST /api/explain — generic ELI5 endpoint ─────────────────────

@app.route("/api/explain", methods=["POST"])
def explain():
    """Generic ELI5: takes 'data_summary' and 'prompt_hint', returns explanation."""
    data = request.get_json(force=True)
    summary = data.get("data_summary", "")
    hint = data.get("prompt_hint", "")
    if not summary:
        abort(400, "Missing 'data_summary'")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    from anthropic import Anthropic

    prompt = (
        f"{hint}\n\nHere is the data:\n\n{summary}\n\n"
        "In 3-4 sentences, give a clear, direct explanation. "
        "Use actual model names and numbers. No jargon."
    )

    try:
        client = Anthropic(api_key=api_key)
        text_parts = []
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                text_parts.append(text)
        return jsonify({"explanation": "".join(text_parts)})
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8000)
