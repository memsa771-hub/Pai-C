-- Spike 3 (throwaway) tables. Idempotent: safe to apply again.
CREATE SCHEMA IF NOT EXISTS spike3;

CREATE TABLE IF NOT EXISTS spike3.tasks (
    id text PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('pending', 'ready', 'running', 'done', 'failed')),
    attempt int NOT NULL DEFAULT 0,
    failure_reason text
);

-- One row per model request, written by the counting model wrapper (append-only).
CREATE TABLE IF NOT EXISTS spike3.model_calls (
    id bigserial PRIMARY KEY,
    task_id text NOT NULL,
    attempt int NOT NULL,
    at timestamptz NOT NULL DEFAULT now()
);

-- Outbox between the kernel (mark_ready) and the enqueuer.
CREATE TABLE IF NOT EXISTS spike3.enqueue_requests (
    task_id text NOT NULL,
    attempt int NOT NULL,
    sent bool NOT NULL DEFAULT false,
    PRIMARY KEY (task_id, attempt)
);

-- One row per task attempt; the primary key makes a re-run insert a no-op.
CREATE TABLE IF NOT EXISTS spike3.results (
    task_id text NOT NULL,
    attempt int NOT NULL,
    output jsonb,
    valid bool NOT NULL,
    PRIMARY KEY (task_id, attempt)
);

-- One row per execution of a spike step (append-only), so re-runs can be counted.
CREATE TABLE IF NOT EXISTS spike3.step_runs (
    id bigserial PRIMARY KEY,
    task_id text NOT NULL,
    attempt int NOT NULL,
    step text NOT NULL,
    at timestamptz NOT NULL DEFAULT now()
);

-- Task 7: which worker process wrote the row (env SPIKE3_WORKER, e.g. `w1g3`; NULL in-process).
ALTER TABLE spike3.step_runs ADD COLUMN IF NOT EXISTS worker text;
ALTER TABLE spike3.model_calls ADD COLUMN IF NOT EXISTS worker text;
