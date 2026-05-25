#!/usr/bin/env python3
"""CI metrics reporter for PostgreSQL + MLflow."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psycopg = None

try:
    import mlflow  # type: ignore
    from mlflow.tracking import MlflowClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mlflow = None
    MlflowClient = None

LOGGER = logging.getLogger("ci_metrics_reporter")

DEFAULT_METRICS: dict[str, float] = {
    "pipeline_duration_seconds": -1,
    "run_failed": 0,
    "detections_total": 0,
    "escalations_total": 0,
    "escalation_rate": -1,
    "edge_latency_p50_ms": -1,
    "edge_latency_p95_ms": -1,
    "cloud_latency_p95_ms": -1,
    "edge_cloud_agreement_rate": -1,
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ci_runs (
    id BIGSERIAL PRIMARY KEY,
    repository TEXT NOT NULL,
    workflow_name TEXT,
    job_name TEXT,
    github_run_id BIGINT NOT NULL,
    github_run_attempt INTEGER NOT NULL DEFAULT 1,
    github_sha TEXT,
    github_ref TEXT,
    github_actor TEXT,
    event_name TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'in_progress',
    run_failed INTEGER NOT NULL DEFAULT 0,
    pipeline_duration_seconds DOUBLE PRECISION,
    partial_metrics BOOLEAN NOT NULL DEFAULT FALSE,
    mlflow_run_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(repository, github_run_id, github_run_attempt)
);

CREATE INDEX IF NOT EXISTS idx_ci_runs_started_at ON ci_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ci_runs_status ON ci_runs(status);

CREATE TABLE IF NOT EXISTS ci_metrics (
    id BIGSERIAL PRIMARY KEY,
    ci_run_id BIGINT NOT NULL REFERENCES ci_runs(id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    metric_step INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'ci',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(ci_run_id, metric_name, metric_step)
);

CREATE INDEX IF NOT EXISTS idx_ci_metrics_metric_name ON ci_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_ci_metrics_recorded_at ON ci_metrics(recorded_at DESC);
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report CI metrics to PostgreSQL and MLflow")
    parser.add_argument("command", choices=["start", "publish", "finalize"])
    parser.add_argument("--metrics-path", default=os.getenv("CI_METRICS_PATH", ""))
    parser.add_argument("--metrics-json", default=os.getenv("CI_METRICS_JSON", ""))
    return parser.parse_args()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class MetricsReporter:
    def __init__(self) -> None:
        self.repository = os.getenv("GITHUB_REPOSITORY", "unknown/unknown")
        self.workflow_name = os.getenv("GITHUB_WORKFLOW", "unknown-workflow")
        self.job_name = os.getenv("GITHUB_JOB", "unknown-job")
        self.github_run_id = safe_int(os.getenv("GITHUB_RUN_ID"), 0)
        self.github_run_attempt = safe_int(os.getenv("GITHUB_RUN_ATTEMPT"), 1)
        self.github_sha = os.getenv("GITHUB_SHA", "")
        self.github_ref = os.getenv("GITHUB_REF", "")
        self.github_actor = os.getenv("GITHUB_ACTOR", "")
        self.event_name = os.getenv("GITHUB_EVENT_NAME", "")

        self.started_at = parse_iso(os.getenv("CI_RUN_STARTED_AT")) or utcnow()
        self.metrics_auto_init_schema = env_bool("CI_METRICS_AUTO_INIT_SCHEMA", default=True)
        self.experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "ci-metrics")

        self.postgres_dsn = os.getenv("POSTGRES_DSN", "")
        self.mlflow_tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "")
        self.mlflow_tracking_token = os.getenv("MLFLOW_TRACKING_TOKEN", "")

    def maybe_connect_db(self):
        if not self.postgres_dsn:
            LOGGER.warning("POSTGRES_DSN is not set; PostgreSQL writes are skipped.")
            return None
        if psycopg is None:
            LOGGER.warning("psycopg is not available; PostgreSQL writes are skipped.")
            return None
        try:
            conn = psycopg.connect(self.postgres_dsn, autocommit=True)
            return conn
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            LOGGER.warning("Could not connect to PostgreSQL: %s", exc)
            return None

    def maybe_mlflow_client(self):
        if not self.mlflow_tracking_uri:
            LOGGER.warning("MLFLOW_TRACKING_URI is not set; MLflow writes are skipped.")
            return None
        if mlflow is None or MlflowClient is None:
            LOGGER.warning("mlflow package is not available; MLflow writes are skipped.")
            return None
        try:
            os.environ.setdefault("MLFLOW_TRACKING_URI", self.mlflow_tracking_uri)
            if self.mlflow_tracking_token:
                os.environ.setdefault("MLFLOW_TRACKING_TOKEN", self.mlflow_tracking_token)
            mlflow.set_tracking_uri(self.mlflow_tracking_uri)
            return MlflowClient(tracking_uri=self.mlflow_tracking_uri)
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            LOGGER.warning("Could not initialize MLflow client: %s", exc)
            return None

    def ensure_schema(self, conn) -> None:
        if conn is None or not self.metrics_auto_init_schema:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
        except Exception as exc:
            LOGGER.warning("Failed ensuring CI schema exists: %s", exc)

    def ensure_run_row(self, conn) -> tuple[int | None, str | None]:
        if conn is None:
            return None, None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ci_runs (
                        repository,
                        workflow_name,
                        job_name,
                        github_run_id,
                        github_run_attempt,
                        github_sha,
                        github_ref,
                        github_actor,
                        event_name,
                        started_at,
                        status,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'in_progress', NOW())
                    ON CONFLICT (repository, github_run_id, github_run_attempt)
                    DO UPDATE SET
                        workflow_name = EXCLUDED.workflow_name,
                        job_name = EXCLUDED.job_name,
                        github_sha = EXCLUDED.github_sha,
                        github_ref = EXCLUDED.github_ref,
                        github_actor = EXCLUDED.github_actor,
                        event_name = EXCLUDED.event_name,
                        updated_at = NOW()
                    RETURNING id, mlflow_run_id
                    """,
                    (
                        self.repository,
                        self.workflow_name,
                        self.job_name,
                        self.github_run_id,
                        self.github_run_attempt,
                        self.github_sha,
                        self.github_ref,
                        self.github_actor,
                        self.event_name,
                        self.started_at,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None, None
                return int(row[0]), row[1]
        except Exception as exc:
            LOGGER.warning("Failed upserting ci_runs row: %s", exc)
            return None, None

    def update_mlflow_run_id(self, conn, ci_run_id: int, mlflow_run_id: str) -> None:
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ci_runs SET mlflow_run_id = %s, updated_at = NOW() WHERE id = %s",
                    (mlflow_run_id, ci_run_id),
                )
        except Exception as exc:
            LOGGER.warning("Failed storing mlflow_run_id: %s", exc)

    def create_mlflow_run_if_needed(self, client, existing_run_id: str | None) -> str | None:
        if client is None:
            return existing_run_id
        if existing_run_id:
            return existing_run_id
        try:
            experiment = client.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                experiment_id = client.create_experiment(self.experiment_name)
            else:
                experiment_id = experiment.experiment_id
            run = client.create_run(
                experiment_id,
                tags={
                    "source": "github-actions",
                    "github.repository": self.repository,
                    "github.run_id": str(self.github_run_id),
                    "github.run_attempt": str(self.github_run_attempt),
                    "github.workflow": self.workflow_name,
                    "github.job": self.job_name,
                },
            )
            return run.info.run_id
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            LOGGER.warning("Failed creating MLflow run: %s", exc)
            return None

    def load_metrics(self, args: argparse.Namespace) -> tuple[dict[str, float], bool]:
        provided: dict[str, Any] = {}

        if args.metrics_json:
            try:
                obj = json.loads(args.metrics_json)
                if isinstance(obj, dict):
                    provided.update(obj)
            except json.JSONDecodeError:
                LOGGER.warning("CI_METRICS_JSON is invalid JSON; falling back to defaults.")

        metrics_path = args.metrics_path
        if metrics_path:
            try:
                with open(metrics_path, "r", encoding="utf-8") as fp:
                    obj = json.load(fp)
                if isinstance(obj, dict):
                    provided.update(obj)
            except FileNotFoundError:
                LOGGER.warning("Metrics file not found at %s; falling back to defaults.", metrics_path)
            except json.JSONDecodeError:
                LOGGER.warning("Metrics file %s has invalid JSON; falling back to defaults.", metrics_path)

        metrics: dict[str, float] = {}
        partial = False

        test_step_outcome = os.getenv("CI_TEST_STEP_OUTCOME", "").strip().lower()
        outcome_unknown = test_step_outcome == ""
        run_failed_default = 0 if test_step_outcome == "success" else 1

        for name, default in DEFAULT_METRICS.items():
            env_key = name.upper()
            raw_value = os.getenv(env_key)
            if raw_value is None:
                raw_value = provided.get(name)
            if raw_value is None and name == "run_failed":
                raw_value = os.getenv("CI_RUN_FAILED", run_failed_default)
            if raw_value is None:
                partial = True
                raw_value = default
            metrics[name] = safe_float(raw_value, default)

        if metrics["run_failed"] not in {0.0, 1.0}:
            metrics["run_failed"] = 1.0 if metrics["run_failed"] > 0 else 0.0
            partial = True

        if outcome_unknown:
            partial = True

        started = self.started_at
        if metrics["pipeline_duration_seconds"] < 0:
            metrics["pipeline_duration_seconds"] = max(0.0, (utcnow() - started).total_seconds())

        if env_bool("CI_METRICS_PARTIAL", default=False):
            partial = True

        return metrics, partial

    def upsert_metrics(self, conn, ci_run_id: int | None, metrics: dict[str, float]) -> None:
        if conn is None or ci_run_id is None:
            return
        try:
            with conn.cursor() as cur:
                for name, value in metrics.items():
                    cur.execute(
                        """
                        INSERT INTO ci_metrics (ci_run_id, metric_name, metric_value, metric_step, source)
                        VALUES (%s, %s, %s, 0, 'ci')
                        ON CONFLICT (ci_run_id, metric_name, metric_step)
                        DO UPDATE SET metric_value = EXCLUDED.metric_value, recorded_at = NOW()
                        """,
                        (ci_run_id, name, value),
                    )
        except Exception as exc:
            LOGGER.warning("Failed upserting ci_metrics rows: %s", exc)

    def log_metrics_mlflow(
        self,
        client,
        mlflow_run_id: str | None,
        metrics: dict[str, float],
        partial: bool,
    ) -> None:
        if client is None or not mlflow_run_id:
            return
        now_ms = int(time.time() * 1000)
        try:
            for name, value in metrics.items():
                client.log_metric(mlflow_run_id, name, float(value), timestamp=now_ms, step=0)
            client.set_tag(mlflow_run_id, "partial_metrics", str(partial).lower())
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            LOGGER.warning("Failed logging MLflow metrics: %s", exc)

    def finalize_run(
        self,
        conn,
        ci_run_id: int | None,
        mlflow_run_id: str | None,
        metrics: dict[str, float],
        partial: bool,
    ) -> None:
        failed = int(1 if metrics.get("run_failed", 0) >= 1 else 0)
        status = os.getenv("CI_FINAL_STATUS")
        if not status:
            status = "failed" if failed else "success"

        if conn is not None and ci_run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ci_runs
                        SET finished_at = NOW(),
                            status = %s,
                            run_failed = %s,
                            pipeline_duration_seconds = %s,
                            partial_metrics = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (status, failed, metrics["pipeline_duration_seconds"], partial, ci_run_id),
                    )
            except Exception as exc:
                LOGGER.warning("Failed finalizing ci_runs row: %s", exc)

        client = self.maybe_mlflow_client()
        if client is not None and mlflow_run_id:
            mlflow_status = "FAILED" if failed else "FINISHED"
            try:
                client.set_tag(mlflow_run_id, "run_status", status)
                client.set_terminated(
                    mlflow_run_id,
                    status=mlflow_status,
                    end_time=int(time.time() * 1000),
                )
            except Exception as exc:  # pragma: no cover - runtime environment dependent
                LOGGER.warning("Failed terminating MLflow run: %s", exc)

    def run(self, args: argparse.Namespace) -> int:
        conn = self.maybe_connect_db()
        self.ensure_schema(conn)
        ci_run_id, mlflow_run_id = self.ensure_run_row(conn)

        client = self.maybe_mlflow_client()
        mlflow_run_id = self.create_mlflow_run_if_needed(client, mlflow_run_id)
        if conn is not None and ci_run_id is not None and mlflow_run_id:
            self.update_mlflow_run_id(conn, ci_run_id, mlflow_run_id)

        if args.command == "start":
            LOGGER.info(
                "Recorded CI run start for %s run_id=%s attempt=%s",
                self.repository,
                self.github_run_id,
                self.github_run_attempt,
            )
            return 0

        metrics, partial = self.load_metrics(args)
        self.upsert_metrics(conn, ci_run_id, metrics)
        self.log_metrics_mlflow(client, mlflow_run_id, metrics, partial)

        if args.command == "finalize":
            self.finalize_run(conn, ci_run_id, mlflow_run_id, metrics, partial)

        LOGGER.info(
            "Reported %s metrics for %s run_id=%s",
            len(metrics),
            self.repository,
            self.github_run_id,
        )
        return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    reporter = MetricsReporter()
    return reporter.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
