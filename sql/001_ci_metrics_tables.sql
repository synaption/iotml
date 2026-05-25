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
