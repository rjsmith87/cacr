"""CACR — Flask backend.

Endpoints (11):
  GET  /                          — service index listing all endpoints
  GET  /health                    — Render health check
  GET  /api/health                — status, model count, task count, total calls
  GET  /api/capability-matrix     — models x tasks x scores heatmap data
  GET  /api/calibration           — confidence vs accuracy scatter data per model
  GET  /api/pipeline-cost         — pipeline strategy comparison
  GET  /api/cost-matrix           — cost_matrix.csv as JSON
  POST /api/route                 — route a prompt to cost-optimal model
  GET  /api/findings              — FINDINGS.md as markdown
  POST /api/explain-calibration   — Claude ELI5 of calibration data
  POST /api/explain               — generic Claude ELI5 endpoint
"""

import csv
import json
import os
import sys
import time

from flask import Flask, jsonify, request, abort
from flask_caching import Cache
from flask_cors import CORS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

app = Flask(__name__)
CORS(app)

# 5-minute in-memory cache for read-heavy BigQuery endpoints. SimpleCache
# is process-local — adequate for our single-gunicorn-worker deployment
# on Render. /health and /api/route are intentionally uncached: the
# former feeds an external uptime monitor that needs to actually probe
# the instance, the latter takes user-unique input every call.
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300})

# Model used for ELI5 explanation endpoints.
EXPLAIN_MODEL = "claude-sonnet-4-20250514"


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


# ── GET / (service index) ──────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "service": "CACR API",
        "endpoints": [
            "/health",
            "/api/health",
            "/api/capability-matrix",
            "/api/calibration",
            "/api/pipeline-cost",
            "/api/cost-matrix",
            "/api/route",
            "/api/findings",
            "/api/explain-calibration",
            "/api/explain",
        ],
        "docs": "https://github.com/rjsmith87/cacr",
        "dashboard": "https://cacr-dashboard.onrender.com",
    })


# ── GET /health (Render health check) ──────────────────────────────

@app.route("/health")
def health_check():
    return {"status": "ok"}


# ── GET /api/health ────────────────────────────────────────────────

@app.route("/api/health")
@cache.cached(timeout=300)
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
@cache.cached(timeout=300)
def capability_matrix():
    try:
        client = _bq_client()
        # Pull the latest summary row for each (task, model) across ALL runs.
        # The previous WHERE run_ts = MAX(run_ts) filter assumed every run
        # contained every model — true for v1 but not for the v2 frontier
        # run that only included the four new models. With this query, the
        # dashboard surfaces the full 8-model matrix from whichever run
        # most recently scored each (task, model) pair.
        rows = list(client.query("""
            SELECT task, model, tier, mean_score, mean_confidence,
                   calibration_r, mean_latency_ms, passes_threshold
            FROM `cacr_results.benchmark_summaries`
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY task, model ORDER BY run_ts DESC
            ) = 1
            ORDER BY task, model
        """).result())
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# ── GET /api/calibration ───────────────────────────────────────────

@app.route("/api/calibration")
@cache.cached(timeout=300)
def calibration():
    try:
        client = _bq_client()
        # For each (model, task) pair, return all calls from that pair's
        # most recent run. Same rationale as /api/capability-matrix: the
        # MAX(run_ts) filter dropped any model not in the latest run, so
        # post-v2 the scatter only showed the four frontier models. This
        # version pulls all 8 models' latest calibration data.
        rows = list(client.query("""
            WITH latest_run_per_pair AS (
                SELECT task, model, MAX(run_ts) AS latest_ts
                FROM `cacr_results.benchmark_calls`
                GROUP BY task, model
            )
            SELECT c.model, c.task, c.difficulty, c.score, c.confidence_score
            FROM `cacr_results.benchmark_calls` c
            JOIN latest_run_per_pair l
              ON c.task = l.task AND c.model = l.model AND c.run_ts = l.latest_ts
            WHERE c.confidence_score IS NOT NULL
            ORDER BY c.model, c.task
        """).result())
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# ── GET /api/pipeline-cost ─────────────────────────────────────────

@app.route("/api/pipeline-cost")
@cache.cached(timeout=300)
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
@cache.cached(timeout=300)
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
    from router.policy import CACRRouter, LookupTableRouter

    task = data.get("task", "CodeReview")
    task_family = data.get("task_family", "classification")

    complexity = data.get("complexity", "auto")
    inferred = None
    if complexity == "auto" or not complexity:
        inferred = infer_complexity(data["prompt"])
        complexity = inferred

    # Try the trained CACRRouter first — it actually consumes complexity
    # (LookupTableRouter is indexed by task only and ignores it). If the
    # classifier isn't trained or fails to load, fall back to the lookup
    # table which still provides a sane cost-matrix-grounded decision.
    cacr = CACRRouter()
    cacr.load()
    if cacr._clf is not None:
        decision = cacr.route(
            data["prompt"],
            task_family=task_family,
            complexity=complexity,
        )
        router_used = "cacr"
    else:
        decision = LookupTableRouter().route(task)
        router_used = "lookup_table"

    resp = {
        "recommended_model": decision.recommended_model,
        "expected_cost": decision.expected_cost,
        "confidence_interval": list(decision.confidence_interval),
        "reasoning": decision.reasoning,
        "complexity": complexity,
        "router": router_used,
    }
    if inferred:
        resp["inferred_complexity"] = inferred
    if decision.below_threshold:
        resp["below_threshold"] = True
        resp["warning"] = decision.warning
    return jsonify(resp)


# ── GET /api/findings ──────────────────────────────────────────────

@app.route("/api/findings")
@cache.cached(timeout=300)
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
            model=EXPLAIN_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                text_parts.append(text)

        return jsonify({"explanation": "".join(text_parts)})
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# ── POST /api/explain — generic ELI5 endpoint ─────────────────────

# Phrases the explain endpoint must NOT use when paired with a below-threshold
# warning. These have shown up in production traffic and are the exact kind
# of misleading framing the warning was added to prevent — "good deal" /
# "rock-bottom pricing" for a model that's wrong more than half the time
# is the bug, not the feature. The "winner / matches performance / same
# result" cluster was added when the same pattern appeared on the Pipeline
# Cost tab. The "smart trade-off / right call / trust the result" cluster
# was added for the Cascade Comparison tool, where confidence-based
# escalation only catches uncertain models — never overconfident wrong
# ones — and the explanation must not paper over that limit.
_BANNED_PHRASES_WHEN_BELOW_THRESHOLD = (
    '"good value", "good deal", "adequate performance", "passes our minimum '
    'standards", "meets our minimum bar", "acceptable quality", "rock-bottom '
    'pricing", "reliable choice", "clear winner", "winner", "matches '
    'performance", "comparable accuracy", "same result", "smart trade-off", '
    '"smart tradeoff", "the right call", "trust the result", "reliable '
    'answer", "best of both worlds", "safely escalated"'
)


# Cascade-comparison contexts. The dashboard's cascade-comparison tab passes
# a `cascade_context` value with the request when the data summary is a
# cascade-pipeline run. The server appends a tailored instruction block to
# the prompt so Claude reads the data through the right lens — without
# trusting the dashboard to fully spell out the framing in `warning`.
_CASCADE_CONTEXT_HINTS = {
    "escalation_fired": (
        "This is a cascade-comparison run where confidence-based escalation "
        "fired on at least one step. Explain plainly: which step escalated, "
        "what the initial vs escalated confidence numbers were, whether the "
        "classification actually changed, and whether the extra cost was "
        "worth it given the outcome. Do not call the escalation a 'smart "
        "trade-off' or 'the right call' — describe what happened and let "
        "the reader judge."
    ),
    "overconfident_wrong": (
        "This is the runtime-confidence blind spot. The two strategies "
        "produced different classifications, but neither one's confidence "
        "ever dropped below the user's threshold, so the cascade router did "
        "not escalate. State this plainly: confidence-based escalation only "
        "catches uncertain models, not overconfident wrong ones. Reference "
        "the actual confidence numbers and the specific disagreement (which "
        "field — severity, vulnerability type, or vulnerable yes/no — "
        "differs between the strategies). Note that this is exactly why CACR "
        "maintains benchmark data as a routing-time safety net alongside "
        "runtime signals — a model with a poor benchmark on this task "
        "shouldn't have been picked for it in the first place. Do not "
        "characterize either model as trustworthy on this snippet."
    ),
    "agreement": (
        "This is the cascade-comparison agreement case: both strategies "
        "produced the same classification, no escalation fired. Explain in "
        "plain English whether the cost difference is meaningful in "
        "practice — quote the actual dollar amounts — and what an "
        "agreement like this does and does not tell you about the routing "
        "decision. Agreement on one snippet is not a guarantee, and the "
        "explanation should say so explicitly."
    ),
}


# ── POST /api/cascade-compare ──────────────────────────────────────
#
# Side-by-side run of the 3-step (severity → detection → fix) pipeline
# under two strategies: "cacr" (cascade-aware router with runtime
# confidence escalation) or any concrete model name in MODEL_COSTS.
# Validates inputs aggressively because this endpoint hits paid
# upstream APIs and accepts free-form code from the request body.
#
# Rate limit: 30-second cooldown per source IP, kept in a process-local
# dict. The Flask app runs with --workers 2 on Render, so a determined
# client could squeeze through at most 2 calls inside the cooldown by
# bouncing between workers — acceptable for an interactive demo tool;
# upgrade to Redis if the endpoint goes truly public.

_CASCADE_RATE_LIMIT_LAST: dict[str, float] = {}
_CASCADE_COOLDOWN_S = 30
_VALID_TASKS = {"CodeReview", "SecurityVuln", "CodeSummarization"}
_MAX_CODE_CHARS = 5000


def _client_ip() -> str:
    """Return the originating client IP, peeling Cloudflare / Render
    forwarded-for headers to find the actual client. Falls back to
    remote_addr if the headers are absent."""
    fwd = (request.headers.get("X-Forwarded-For") or "").strip()
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


@app.route("/api/cascade-compare", methods=["POST"])
def cascade_compare():
    ip = _client_ip()
    now = time.time()
    last = _CASCADE_RATE_LIMIT_LAST.get(ip, 0.0)
    elapsed = now - last
    if elapsed < _CASCADE_COOLDOWN_S:
        retry_in = round(_CASCADE_COOLDOWN_S - elapsed)
        resp = jsonify({
            "error": f"rate limited: {retry_in}s cooldown remaining",
            "retry_in_seconds": retry_in,
        })
        resp.headers["Retry-After"] = str(retry_in)
        return resp, 429

    data = request.get_json(force=True, silent=True) or {}

    # ── Validate inputs ────────────────────────────────────────────
    code = data.get("code_snippet")
    if not isinstance(code, str) or not code.strip():
        abort(400, "code_snippet (non-empty string) is required")
    if len(code) > _MAX_CODE_CHARS:
        abort(400, f"code_snippet exceeds {_MAX_CODE_CHARS} character limit")

    task = data.get("task")
    if task not in _VALID_TASKS:
        abort(400, f"task must be one of: {sorted(_VALID_TASKS)}")

    from router.cost_model import MODEL_COSTS
    valid_model_names = set(MODEL_COSTS.keys())
    for key in ("strategy_a", "strategy_b"):
        s = data.get(key)
        if s != "cacr" and s not in valid_model_names:
            abort(
                400,
                f"{key} must be 'cacr' or one of: {sorted(valid_model_names)}",
            )

    threshold = data.get("escalation_threshold", 7)
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        abort(400, "escalation_threshold must be a number")
    if not 1 <= threshold <= 10:
        abort(400, "escalation_threshold must be between 1 and 10")

    # ── Stamp the cooldown BEFORE running so a slow / failing
    # request still counts against the client's quota. Prevents
    # spam-retrying a 500. ──────────────────────────────────────────
    _CASCADE_RATE_LIMIT_LAST[ip] = now

    try:
        from pipelines.cascade_pipeline import run_pipeline
        result = run_pipeline(
            code_snippet=code,
            task=task,
            strategy_a=data["strategy_a"],
            strategy_b=data["strategy_b"],
            escalation_threshold=threshold,
        )
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/explain", methods=["POST"])
def explain():
    """ELI5: takes 'data_summary' + 'prompt_hint' and optional structured
    'task_name' / 'warning' fields. When `task_name` is supplied it is
    referenced verbatim in the prompt so the model paraphrase can't drift to
    the wrong task. When `warning` is supplied (router below-threshold path),
    the prompt template forces honest framing and bans the marketing-style
    phrases that previously slipped into low-score explanations."""
    data = request.get_json(force=True)
    summary = data.get("data_summary", "")
    hint = data.get("prompt_hint", "")
    task_name = data.get("task_name")
    warning = data.get("warning")
    cascade_context = data.get("cascade_context")
    if not summary:
        abort(400, "Missing 'data_summary'")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    from anthropic import Anthropic

    # Build the prompt. Task name (when supplied) is pinned at the top so
    # Claude can't paraphrase to the wrong task by reading a buried "Task:"
    # line in the data summary. Warning (when supplied) takes priority over
    # the optimistic prompt_hint and explicitly forbids marketing language.
    parts: list[str] = []
    if task_name:
        parts.append(
            f"The task the user submitted is exactly: {task_name}. "
            f"Reference this task name (or its natural-language paraphrase) "
            f"in your explanation. Do NOT substitute a different task."
        )
    if warning:
        parts.append(
            f"IMPORTANT — honest framing required:\n{warning}\n\n"
            f"All evaluated options perform poorly on this task. Your "
            f"explanation MUST call this out plainly and recommend caution "
            f"(human review, escalation to a more capable option, or task "
            f"reformulation). Do NOT use any of these phrases: "
            f"{_BANNED_PHRASES_WHEN_BELOW_THRESHOLD}. Do not characterize "
            f"any option as a good choice; characterize the recommended one "
            f"as the least-bad available option, and say so."
        )
    if cascade_context and cascade_context in _CASCADE_CONTEXT_HINTS:
        # Cascade-specific framing layered on top of the generic warning
        # block when the dashboard's cascade-comparison tool is the
        # caller. Banned-phrases instruction also applies to this context
        # so the explanation can't slip into "smart trade-off" framing.
        parts.append(
            f"CASCADE CONTEXT — {cascade_context}:\n"
            f"{_CASCADE_CONTEXT_HINTS[cascade_context]}\n\n"
            f"Banned phrases (do not use): "
            f"{_BANNED_PHRASES_WHEN_BELOW_THRESHOLD}."
        )
    if hint:
        parts.append(hint)
    parts.append(f"Here is the data:\n\n{summary}")
    parts.append(
        "In 3-4 sentences, give a clear, direct explanation. "
        "Use actual model names and numbers. No jargon."
    )
    prompt = "\n\n".join(parts)

    try:
        client = Anthropic(api_key=api_key)
        text_parts = []
        with client.messages.stream(
            model=EXPLAIN_MODEL,
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
