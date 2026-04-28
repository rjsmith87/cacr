"""BigQuery writer for CACR benchmark + Phase 2 results.

Creates dataset/tables if they don't exist, adds any new columns to
existing tables (idempotent), then streams rows via the insertAll API.

Credential strategy (Render vs local split):
  1. If GOOGLE_APPLICATION_CREDENTIALS_JSON is set, parse the JSON string
     and build credentials from service_account.Credentials. Render path.
  2. Otherwise fall back to Application Default Credentials (ADC), which
     works locally after `gcloud auth application-default login`.

Tables (Phase 2):
  benchmark_calls          — existing, now extended with Phase-2 columns
  benchmark_summaries      — existing, unchanged
  cve_study_calls          — NEW per-CVE per-model call with calibration metrics
  model_calibration_summary— NEW per-model rollup with dangerous_rate, ECE
  live_trace_calls         — NEW routed calls from the live feature (hashed)
  fine_tune_training_set   — NEW curated training examples (Phase 3)
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery


def _build_bq_client(project: str) -> bigquery.Client:
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        from google.oauth2 import service_account
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        return bigquery.Client(project=project, credentials=creds)
    return bigquery.Client(project=project)


# ── Dataset / table names ──────────────────────────────────────────────
DATASET = "cacr_results"
TABLE_CALLS = "benchmark_calls"
TABLE_SUMMARIES = "benchmark_summaries"
TABLE_CVE = "cve_study_calls"
TABLE_CALIBRATION = "model_calibration_summary"
TABLE_LIVE_TRACE = "live_trace_calls"
TABLE_FINETUNE = "fine_tune_training_set"


# ── Schemas ────────────────────────────────────────────────────────────
# benchmark_calls: existing columns + 10 Phase-2 additions. Existing tables
# in BQ will have the new columns appended via _ensure_schema_current.
CALLS_SCHEMA = [
    bigquery.SchemaField("run_ts", "TIMESTAMP"),
    bigquery.SchemaField("event", "STRING"),
    bigquery.SchemaField("task", "STRING"),
    bigquery.SchemaField("family", "STRING"),
    bigquery.SchemaField("difficulty", "STRING"),
    bigquery.SchemaField("model", "STRING"),
    bigquery.SchemaField("tier", "INTEGER"),
    bigquery.SchemaField("example_idx", "INTEGER"),
    bigquery.SchemaField("latency_ms", "FLOAT"),
    bigquery.SchemaField("score", "FLOAT"),
    bigquery.SchemaField("confidence_score", "INTEGER"),
    bigquery.SchemaField("output", "STRING"),
    bigquery.SchemaField("error", "STRING"),
    # ── Phase-2 additions (all NULLABLE for backward compat) ──
    bigquery.SchemaField("source", "STRING",
                         description="'batch_run' | 'live_trace' | 'user_submission'"),
    bigquery.SchemaField("user_snippet", "BOOL",
                         description="True if pasted by user vs authored"),
    bigquery.SchemaField("session_id", "STRING",
                         description="Groups pipeline calls together"),
    bigquery.SchemaField("routing_decision", "STRING",
                         description="Which model selected and why"),
    bigquery.SchemaField("cascade_triggered", "BOOL",
                         description="Did router escalate?"),
    bigquery.SchemaField("thinking_tokens_disabled", "BOOL",
                         description="Was reasoning mode off for this call?"),
    bigquery.SchemaField("model_version", "STRING",
                         description="Exact model version string"),
    bigquery.SchemaField("adapter_config", "JSON",
                         description="max_tokens, pacing, thinking_budget, etc."),
    bigquery.SchemaField("task_family", "STRING",
                         description="'security' | 'code_review' | 'cve_study'"),
    bigquery.SchemaField("run_phase", "STRING",
                         description="'phase1' | 'phase2_cve' | 'phase3_finetune'"),
]

SUMMARIES_SCHEMA = [
    bigquery.SchemaField("run_ts", "TIMESTAMP"),
    bigquery.SchemaField("event", "STRING"),
    bigquery.SchemaField("task", "STRING"),
    bigquery.SchemaField("family", "STRING"),
    bigquery.SchemaField("model", "STRING"),
    bigquery.SchemaField("tier", "INTEGER"),
    bigquery.SchemaField("n", "INTEGER"),
    bigquery.SchemaField("mean_score", "FLOAT"),
    bigquery.SchemaField("mean_confidence", "FLOAT"),
    bigquery.SchemaField("calibration_r", "FLOAT"),
    bigquery.SchemaField("calibration_by_difficulty", "STRING"),
    bigquery.SchemaField("mean_latency_ms", "FLOAT"),
    bigquery.SchemaField("threshold", "FLOAT"),
    bigquery.SchemaField("passes_threshold", "BOOLEAN"),
    bigquery.SchemaField("cost_per_token", "FLOAT"),
]

CVE_STUDY_SCHEMA = [
    bigquery.SchemaField("call_id", "STRING"),
    bigquery.SchemaField("run_id", "STRING"),
    bigquery.SchemaField("cve_id", "STRING"),
    bigquery.SchemaField("language", "STRING", description="python | java | javascript"),
    bigquery.SchemaField("severity_gold", "STRING", description="CVSS-banded NVD"),
    bigquery.SchemaField("vuln_class_gold", "STRING", description="OWASP-aligned taxonomy"),
    bigquery.SchemaField("model_name", "STRING"),
    bigquery.SchemaField("model_version", "STRING"),
    bigquery.SchemaField("vuln_class_predicted", "STRING"),
    bigquery.SchemaField("severity_predicted", "STRING"),
    bigquery.SchemaField("confidence_reported", "INTEGER", description="0-10 self-reported"),
    bigquery.SchemaField("vuln_class_correct", "BOOL"),
    bigquery.SchemaField("severity_correct", "BOOL"),
    bigquery.SchemaField("both_correct", "BOOL"),
    bigquery.SchemaField("off_by_one_severity", "BOOL"),
    bigquery.SchemaField("dangerous_rate_event", "BOOL",
                         description="Wrong AND confidence >= 8"),
    bigquery.SchemaField("silent_miss_event", "BOOL",
                         description="Severity underestimated AND confidence >= 7"),
    bigquery.SchemaField("overconfidence_score", "FLOAT",
                         description="conf_norm * (1 - correct)"),
    bigquery.SchemaField("cascade_cost_usd", "FLOAT",
                         description="Computed expected cost"),
    bigquery.SchemaField("routellm_decision", "STRING",
                         description="What RouteLLM would have picked"),
    bigquery.SchemaField("thinking_tokens_disabled", "BOOL"),
    bigquery.SchemaField("latency_ms", "INTEGER"),
    bigquery.SchemaField("input_tokens", "INTEGER"),
    bigquery.SchemaField("output_tokens", "INTEGER"),
    bigquery.SchemaField("cost_usd", "FLOAT"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
    bigquery.SchemaField("run_phase", "STRING"),
]

CALIBRATION_SUMMARY_SCHEMA = [
    bigquery.SchemaField("summary_id", "STRING"),
    bigquery.SchemaField("run_id", "STRING"),
    bigquery.SchemaField("model_name", "STRING"),
    bigquery.SchemaField("model_version", "STRING"),
    bigquery.SchemaField("task_family", "STRING"),
    bigquery.SchemaField("run_phase", "STRING"),
    bigquery.SchemaField("n_calls", "INTEGER"),
    bigquery.SchemaField("accuracy", "FLOAT"),
    bigquery.SchemaField("dangerous_rate", "FLOAT"),
    bigquery.SchemaField("silent_miss_rate", "FLOAT"),
    bigquery.SchemaField("overconfidence_score", "FLOAT"),
    bigquery.SchemaField("ece_10bin", "FLOAT",
                         description="Expected calibration error, 10 equal-width bins"),
    bigquery.SchemaField("expected_cost_per_call_usd", "FLOAT"),
    bigquery.SchemaField("expected_cost_with_cascade_usd", "FLOAT"),
    bigquery.SchemaField("routellm_dangerous_rate", "FLOAT"),
    bigquery.SchemaField("cacr_wins_on_dangerous_rate", "BOOL"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
    bigquery.SchemaField("notes", "STRING"),
]

LIVE_TRACE_SCHEMA = [
    bigquery.SchemaField("trace_id", "STRING"),
    bigquery.SchemaField("session_id", "STRING"),
    bigquery.SchemaField("user_snippet_hash", "STRING",
                         description="Hashed for privacy, never raw"),
    bigquery.SchemaField("language_detected", "STRING"),
    bigquery.SchemaField("task_family_detected", "STRING"),
    bigquery.SchemaField("routing_decision", "STRING"),
    bigquery.SchemaField("model_selected", "STRING"),
    bigquery.SchemaField("model_version", "STRING"),
    bigquery.SchemaField("vuln_class_predicted", "STRING"),
    bigquery.SchemaField("severity_predicted", "STRING"),
    bigquery.SchemaField("confidence_reported", "INTEGER"),
    bigquery.SchemaField("dangerous_rate_flag", "BOOL",
                         description="Flagged as high risk?"),
    bigquery.SchemaField("cascade_cost_estimate_usd", "FLOAT"),
    bigquery.SchemaField("latency_ms", "INTEGER"),
    bigquery.SchemaField("cost_usd", "FLOAT"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
    bigquery.SchemaField("contributed_to_training", "BOOL",
                         description="Will this feed the fine-tune?"),
]

FINETUNE_SCHEMA = [
    bigquery.SchemaField("example_id", "STRING"),
    bigquery.SchemaField("source", "STRING",
                         description="'cve_battery' | 'live_trace' | 'nvd_pull'"),
    bigquery.SchemaField("cve_id", "STRING", description="Null if live_trace"),
    bigquery.SchemaField("language", "STRING"),
    bigquery.SchemaField("snippet_hash", "STRING", description="Hashed for privacy"),
    bigquery.SchemaField("vuln_class_gold", "STRING"),
    bigquery.SchemaField("severity_gold", "STRING"),
    bigquery.SchemaField("confidence_gold", "INTEGER", description="Human verified"),
    bigquery.SchemaField("included_in_run", "STRING",
                         description="Which fine-tune run used this"),
    bigquery.SchemaField("quality_score", "FLOAT",
                         description="Inter-rater agreement if available"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
]


# ── Table creation / schema migration ─────────────────────────────────
def _ensure_schema_current(
    client: bigquery.Client,
    table: bigquery.Table,
    desired_schema: list[bigquery.SchemaField],
) -> bigquery.Table:
    """Append any missing columns to an existing table. Idempotent.

    BigQuery supports appending NULLABLE columns to an existing schema
    without rewriting data. We never drop or retype existing columns.
    """
    existing_names = {f.name for f in table.schema}
    missing = [f for f in desired_schema if f.name not in existing_names]
    if not missing:
        return table
    new_schema = list(table.schema) + missing
    table.schema = new_schema
    return client.update_table(table, ["schema"])


def _ensure_table(
    client: bigquery.Client,
    dataset_ref: bigquery.DatasetReference,
    table_id: str,
    schema: list[bigquery.SchemaField],
) -> bigquery.Table:
    table_ref = dataset_ref.table(table_id)
    table = bigquery.Table(table_ref, schema=schema)
    table = client.create_table(table, exists_ok=True)
    return _ensure_schema_current(client, table, schema)


def _ensure_all_tables(
    client: bigquery.Client, project: str, dataset: str
) -> dict[str, bigquery.Table]:
    dataset_ref = bigquery.DatasetReference(project, dataset)
    ds = bigquery.Dataset(dataset_ref)
    ds.location = "US"
    client.create_dataset(ds, exists_ok=True)
    return {
        TABLE_CALLS: _ensure_table(client, dataset_ref, TABLE_CALLS, CALLS_SCHEMA),
        TABLE_SUMMARIES: _ensure_table(client, dataset_ref, TABLE_SUMMARIES, SUMMARIES_SCHEMA),
        TABLE_CVE: _ensure_table(client, dataset_ref, TABLE_CVE, CVE_STUDY_SCHEMA),
        TABLE_CALIBRATION: _ensure_table(client, dataset_ref, TABLE_CALIBRATION,
                                         CALIBRATION_SUMMARY_SCHEMA),
        TABLE_LIVE_TRACE: _ensure_table(client, dataset_ref, TABLE_LIVE_TRACE,
                                        LIVE_TRACE_SCHEMA),
        TABLE_FINETUNE: _ensure_table(client, dataset_ref, TABLE_FINETUNE, FINETUNE_SCHEMA),
    }


def _project_row(row: dict, schema: list[bigquery.SchemaField]) -> dict:
    """Pick only schema fields from row; missing fields → None.

    JSON-typed fields get json.dumps() if a dict/list is passed.
    """
    out: dict[str, Any] = {}
    for field in schema:
        val = row.get(field.name)
        if field.field_type == "JSON" and val is not None and not isinstance(val, str):
            val = json.dumps(val)
        out[field.name] = val
    return out


def _insert(client: bigquery.Client, table: bigquery.Table, rows: list[dict],
            label: str) -> int:
    if not rows:
        return 0
    errors = client.insert_rows_json(table, rows)
    if errors:
        raise RuntimeError(f"BQ insert errors ({label}): {errors}")
    return len(rows)


def _existing_call_keys(
    client: bigquery.Client, project: str, dataset: str, run_ts: str
) -> set[tuple[str, str, int]]:
    """Existing (task, model, example_idx) tuples for a given run_ts."""
    query = f"""
    SELECT task, model, example_idx
    FROM `{project}.{dataset}.{TABLE_CALLS}`
    WHERE run_ts = @run_ts AND event = 'call'
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_ts", "TIMESTAMP", run_ts),
        ]
    )
    return {
        (r["task"], r["model"], r["example_idx"])
        for r in client.query(query, job_config=job_config).result()
    }


def _existing_summary_keys(
    client: bigquery.Client, project: str, dataset: str, run_ts: str
) -> set[tuple[str, str]]:
    """Existing (task, model) tuples for a given run_ts."""
    query = f"""
    SELECT task, model
    FROM `{project}.{dataset}.{TABLE_SUMMARIES}`
    WHERE run_ts = @run_ts AND event = 'summary'
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_ts", "TIMESTAMP", run_ts),
        ]
    )
    return {
        (r["task"], r["model"])
        for r in client.query(query, job_config=job_config).result()
    }


# ── Public write API ──────────────────────────────────────────────────
def write_rows(
    rows: list[dict[str, Any]],
    project: str,
    dataset: str = DATASET,
    run_ts: str | None = None,
) -> int:
    """Write call + summary rows. Idempotent within a fixed `run_ts`.

    When `run_ts` is supplied, the writer first queries the destination
    tables for existing (task, model, example_idx) and (task, model)
    tuples under that timestamp, and skips rows that are already
    present. This makes replay and partial-rerun safe — the same log
    can be replayed multiple times, and a partial re-run will append
    only the missing examples.

    Phase-2 columns on benchmark_calls are optional; pass them if available.
    """
    client = _build_bq_client(project)
    tables = _ensure_all_tables(client, project, dataset)
    if run_ts is None:
        run_ts = datetime.now(timezone.utc).isoformat()

    call_rows = []
    summary_rows = []
    for row in rows:
        event = row.get("event")
        base = {"run_ts": run_ts, **row}
        if event == "call":
            call_rows.append(_project_row(base, CALLS_SCHEMA))
        elif event == "summary":
            cal_diff = row.get("calibration_by_difficulty")
            r = dict(base)
            if cal_diff is not None and not isinstance(cal_diff, str):
                r["calibration_by_difficulty"] = json.dumps(cal_diff)
            summary_rows.append(_project_row(r, SUMMARIES_SCHEMA))

    # Dedup against rows already in the destination tables for this run_ts.
    # Skip the dedup query when there's nothing to filter (cheaper).
    if call_rows:
        existing = _existing_call_keys(client, project, dataset, run_ts)
        call_rows = [
            r for r in call_rows
            if (r["task"], r["model"], r["example_idx"]) not in existing
        ]
    if summary_rows:
        existing = _existing_summary_keys(client, project, dataset, run_ts)
        summary_rows = [
            r for r in summary_rows
            if (r["task"], r["model"]) not in existing
        ]

    written = 0
    written += _insert(client, tables[TABLE_CALLS], call_rows, "calls")
    written += _insert(client, tables[TABLE_SUMMARIES], summary_rows, "summaries")
    return written


def write_cve_study_rows(
    rows: list[dict[str, Any]],
    project: str,
    dataset: str = DATASET,
) -> int:
    """Write per-CVE per-model calls to cve_study_calls."""
    client = _build_bq_client(project)
    tables = _ensure_all_tables(client, project, dataset)
    projected = [_project_row(r, CVE_STUDY_SCHEMA) for r in rows]
    return _insert(client, tables[TABLE_CVE], projected, "cve_study")


def write_calibration_summary_rows(
    rows: list[dict[str, Any]],
    project: str,
    dataset: str = DATASET,
) -> int:
    """Write per-model calibration rollups to model_calibration_summary."""
    client = _build_bq_client(project)
    tables = _ensure_all_tables(client, project, dataset)
    projected = [_project_row(r, CALIBRATION_SUMMARY_SCHEMA) for r in rows]
    return _insert(client, tables[TABLE_CALIBRATION], projected, "calibration")


def write_live_trace_rows(
    rows: list[dict[str, Any]],
    project: str,
    dataset: str = DATASET,
) -> int:
    """Write live routing trace rows to live_trace_calls.

    Callers MUST hash `user_snippet_hash` upstream; raw snippets never leave
    the process boundary.
    """
    client = _build_bq_client(project)
    tables = _ensure_all_tables(client, project, dataset)
    projected = [_project_row(r, LIVE_TRACE_SCHEMA) for r in rows]
    return _insert(client, tables[TABLE_LIVE_TRACE], projected, "live_trace")


def write_finetune_rows(
    rows: list[dict[str, Any]],
    project: str,
    dataset: str = DATASET,
) -> int:
    """Write curated training examples to fine_tune_training_set."""
    client = _build_bq_client(project)
    tables = _ensure_all_tables(client, project, dataset)
    projected = [_project_row(r, FINETUNE_SCHEMA) for r in rows]
    return _insert(client, tables[TABLE_FINETUNE], projected, "finetune")
