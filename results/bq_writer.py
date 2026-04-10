"""BigQuery writer for CACR benchmark results.

Creates dataset/table if they don't exist, then streams rows via the
insertAll API.

Credential strategy (Render vs local split):
  1. If GOOGLE_APPLICATION_CREDENTIALS_JSON is set, parse the JSON string
     and build credentials from service_account.Credentials.  This is the
     Render path — the SA key JSON is stored as an env var because Render
     has no filesystem-based ADC.
  2. Otherwise fall back to Application Default Credentials (ADC), which
     works locally after `gcloud auth application-default login`.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery


def _build_bq_client(project: str) -> bigquery.Client:
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        # Render path: SA key JSON stored in env var
        from google.oauth2 import service_account
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        return bigquery.Client(project=project, credentials=creds)
    # Local path: ADC (gcloud auth application-default login)
    return bigquery.Client(project=project)

DATASET = "cacr_results"
TABLE_CALLS = "benchmark_calls"
TABLE_SUMMARIES = "benchmark_summaries"

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
    bigquery.SchemaField("calibration_by_difficulty", "STRING"),  # JSON string
    bigquery.SchemaField("mean_latency_ms", "FLOAT"),
    bigquery.SchemaField("threshold", "FLOAT"),
    bigquery.SchemaField("passes_threshold", "BOOLEAN"),
    bigquery.SchemaField("cost_per_token", "FLOAT"),
]


def _ensure_table(
    client: bigquery.Client,
    dataset_ref: bigquery.DatasetReference,
    table_id: str,
    schema: list[bigquery.SchemaField],
) -> bigquery.Table:
    table_ref = dataset_ref.table(table_id)
    table = bigquery.Table(table_ref, schema=schema)
    table = client.create_table(table, exists_ok=True)
    return table


def write_rows(
    rows: list[dict[str, Any]],
    project: str,
    dataset: str = DATASET,
) -> int:
    """Write call + summary rows to BigQuery. Returns total rows written."""
    client = _build_bq_client(project)

    dataset_ref = bigquery.DatasetReference(project, dataset)
    ds = bigquery.Dataset(dataset_ref)
    ds.location = "US"
    client.create_dataset(ds, exists_ok=True)

    calls_table = _ensure_table(client, dataset_ref, TABLE_CALLS, CALLS_SCHEMA)
    summaries_table = _ensure_table(client, dataset_ref, TABLE_SUMMARIES, SUMMARIES_SCHEMA)

    run_ts = datetime.now(timezone.utc).isoformat()

    call_rows = []
    summary_rows = []

    for row in rows:
        event = row.get("event")
        if event == "call":
            call_rows.append({
                "run_ts": run_ts,
                "event": event,
                "task": row.get("task"),
                "family": row.get("family"),
                "difficulty": row.get("difficulty"),
                "model": row.get("model"),
                "tier": row.get("tier"),
                "example_idx": row.get("example_idx"),
                "latency_ms": row.get("latency_ms"),
                "score": row.get("score"),
                "confidence_score": row.get("confidence_score"),
                "output": row.get("output"),
                "error": row.get("error"),
            })
        elif event == "summary":
            cal_diff = row.get("calibration_by_difficulty")
            summary_rows.append({
                "run_ts": run_ts,
                "event": event,
                "task": row.get("task"),
                "family": row.get("family"),
                "model": row.get("model"),
                "tier": row.get("tier"),
                "n": row.get("n"),
                "mean_score": row.get("mean_score"),
                "mean_confidence": row.get("mean_confidence"),
                "calibration_r": row.get("calibration_r"),
                "calibration_by_difficulty": json.dumps(cal_diff) if cal_diff else None,
                "mean_latency_ms": row.get("mean_latency_ms"),
                "threshold": row.get("threshold"),
                "passes_threshold": row.get("passes_threshold"),
                "cost_per_token": row.get("cost_per_token"),
            })

    written = 0
    if call_rows:
        errors = client.insert_rows_json(calls_table, call_rows)
        if errors:
            raise RuntimeError(f"BQ insert errors (calls): {errors}")
        written += len(call_rows)

    if summary_rows:
        errors = client.insert_rows_json(summaries_table, summary_rows)
        if errors:
            raise RuntimeError(f"BQ insert errors (summaries): {errors}")
        written += len(summary_rows)

    return written
