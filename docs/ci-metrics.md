# CI + Metrics Tracking Scaffold

This repository includes a minimal CI scaffold that always emits pipeline metrics to PostgreSQL and MLflow, even when test/inference execution fails.

## Files added

- `.github/workflows/ci-metrics.yml`
- `scripts/ci_metrics_reporter.py`
- `sql/001_ci_metrics_tables.sql`

## Required secrets / environment variables

Configure these repository secrets for full persistence:

| Name | Required | Purpose |
|---|---|---|
| `POSTGRES_DSN` | Yes (for PostgreSQL writes) | PostgreSQL DSN (for example: `postgresql://user:pass@host:5432/dbname`) |
| `MLFLOW_TRACKING_URI` | Yes (for MLflow writes) | MLflow tracking server URI |
| `MLFLOW_TRACKING_TOKEN` | Optional | Token for authenticated MLflow endpoints |

Optional tuning variables:

| Name | Default | Purpose |
|---|---|---|
| `MLFLOW_EXPERIMENT_NAME` | `ci-metrics` | MLflow experiment name |
| `CI_METRICS_AUTO_INIT_SCHEMA` | `1` | Auto-create CI tracking tables if missing |

## Failure-tolerant behavior

The workflow records a `ci_runs` row at start, runs test/inference with `continue-on-error`, then always executes metrics publication/finalization (`if: always()`).

Final pass/fail signaling is preserved by a last step that exits non-zero when the test/inference step failed. This means CI still reports failure while metrics are retained.

## Initial metrics tracked

At minimum, the workflow/script tracks and stores these metrics in both PostgreSQL and MLflow:

- `pipeline_duration_seconds`
- `run_failed` (0/1)
- `detections_total`
- `escalations_total`
- `escalation_rate`
- `edge_latency_p50_ms`
- `edge_latency_p95_ms`
- `cloud_latency_p95_ms`
- `edge_cloud_agreement_rate`

Defaults are used when upstream metrics are unavailable (`0` for counts, `-1` for sentinel unknown values). Runs with partial/defaulted metrics are tagged via `partial_metrics`.

## PostgreSQL bootstrap

Apply the schema manually if preferred:

```bash
psql "$POSTGRES_DSN" -f sql/001_ci_metrics_tables.sql
```

Tables:

- `ci_runs`: one row per GitHub workflow run + attempt, including status and duration
- `ci_metrics`: metric time-series rows keyed to `ci_runs`

## Query examples

Recent runs:

```sql
SELECT
  repository,
  github_run_id,
  github_run_attempt,
  status,
  run_failed,
  pipeline_duration_seconds,
  started_at,
  finished_at
FROM ci_runs
ORDER BY started_at DESC
LIMIT 20;
```

Trend view for a metric:

```sql
SELECT
  r.started_at,
  m.metric_value
FROM ci_metrics m
JOIN ci_runs r ON r.id = m.ci_run_id
WHERE m.metric_name = 'edge_latency_p95_ms'
ORDER BY r.started_at;
```

Failure rate trend:

```sql
SELECT
  date_trunc('day', started_at) AS day,
  AVG(run_failed::float) AS failure_rate
FROM ci_runs
GROUP BY 1
ORDER BY 1;
```

## MLflow inspection

Use your tracking UI for experiment `ci-metrics` (or `MLFLOW_EXPERIMENT_NAME`).

Each workflow attempt maps to one MLflow run tagged with:

- `github.repository`
- `github.run_id`
- `github.run_attempt`
- `github.workflow`
- `github.job`
- `partial_metrics`
