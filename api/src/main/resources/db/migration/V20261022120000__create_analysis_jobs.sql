-- ERD v6 section 31: administrator ingest/revalidate/project jobs and the internal graph projection outbox (#132, #133).
--
-- The public job id is `analysis_jobs.id`; the internal AI job ids a job submits are kept in `checkpoint.aiUnits[]`
-- ({unitKey, aiJobId, submitArtifactId, runtimeInputDigest?}), so one application job may own several AI jobs. An
-- administrator retry is a new row with `retry_of`; a worker's own re-claims are elements of `attempts`. The worker that moves
-- a job from queued to a result (owner token, lease, next attempt, AI submission) is a later change; this migration already
-- holds its columns so the stored contract does not change under it.

CREATE TABLE analysis_jobs (
    id text PRIMARY KEY,
    kind text NOT NULL,
    scope text NOT NULL,
    label text NOT NULL,
    status text NOT NULL,
    reason text NOT NULL,
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    retry_of text,
    command_key text NOT NULL,
    input jsonb NOT NULL,
    checkpoint jsonb,
    target_version_id text,
    cancel_requested boolean NOT NULL DEFAULT false,
    recovered boolean NOT NULL DEFAULT false,
    report jsonb,
    ingest jsonb,
    flush jsonb,
    error jsonb,
    ledger_before jsonb,
    ledger_after jsonb,
    attempts jsonb NOT NULL DEFAULT '[]'::jsonb,
    owner_token text,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    CONSTRAINT uq_analysis_jobs_command_key UNIQUE (command_key),
    CONSTRAINT fk_analysis_jobs_retry_of FOREIGN KEY (retry_of) REFERENCES analysis_jobs (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_analysis_jobs_target_version FOREIGN KEY (target_version_id) REFERENCES graph_versions (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_analysis_jobs_id CHECK (id ~ '^job-[A-Za-z0-9_-]{8,64}$'),
    CONSTRAINT ck_analysis_jobs_kind CHECK (kind IN ('ingest', 'revalidate', 'project')),
    CONSTRAINT ck_analysis_jobs_scope CHECK (scope IN ('admin', 'internal_projection')),
    CONSTRAINT ck_analysis_jobs_projection_kind CHECK (scope <> 'internal_projection' OR kind = 'project'),
    CONSTRAINT ck_analysis_jobs_status CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    -- A started job has a start; a finished job has both ends in order; a queued job has neither.
    CONSTRAINT ck_analysis_jobs_times CHECK (
        (status = 'queued' AND started_at IS NULL AND finished_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND started_at IS NOT NULL AND finished_at IS NOT NULL
            AND finished_at >= started_at)
        OR (status = 'cancelled' AND finished_at IS NOT NULL
            AND (started_at IS NULL OR finished_at >= started_at))
    ),
    CONSTRAINT ck_analysis_jobs_started_after_request CHECK (started_at IS NULL OR started_at >= requested_at),
    CONSTRAINT ck_analysis_jobs_not_own_retry CHECK (retry_of IS NULL OR retry_of <> id),
    CONSTRAINT ck_analysis_jobs_input_object CHECK (jsonb_typeof(input) = 'object'),
    CONSTRAINT ck_analysis_jobs_attempts_array CHECK (jsonb_typeof(attempts) = 'array'),
    CONSTRAINT ck_analysis_jobs_error_object CHECK (error IS NULL OR jsonb_typeof(error) = 'object'),
    CONSTRAINT ck_analysis_jobs_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
    -- A run lease is one owner and one deadline together, and only a running job holds one.
    CONSTRAINT ck_analysis_jobs_lease_pair CHECK ((owner_token IS NULL) = (lease_until IS NULL)),
    CONSTRAINT ck_analysis_jobs_lease_running CHECK (owner_token IS NULL OR status = 'running')
);

-- At most one administrator job holds the run slot; queued jobs wait in request order.
CREATE UNIQUE INDEX uq_analysis_jobs_admin_running ON analysis_jobs (scope) WHERE scope = 'admin' AND status = 'running';
CREATE INDEX ix_analysis_jobs_admin_queue ON analysis_jobs (requested_at, id) WHERE scope = 'admin' AND status = 'queued';
CREATE INDEX ix_analysis_jobs_admin_latest ON analysis_jobs (requested_at DESC, id DESC) WHERE scope = 'admin';
CREATE INDEX ix_analysis_jobs_retry_of ON analysis_jobs (retry_of) WHERE retry_of IS NOT NULL;
CREATE INDEX ix_analysis_jobs_admin_succeeded_input ON analysis_jobs (kind, md5(input::text))
    WHERE scope = 'admin' AND status = 'succeeded';

-- ERD v6 section 31: the initial command is fixed when the job is requested. The worker only moves status, times, lease,
-- checkpoint and results; an administrator retry is a new row, never an edit of this one.
CREATE FUNCTION analysis_jobs_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.kind, NEW.scope, NEW.label, NEW.reason, NEW.requested_by, NEW.requested_at, NEW.retry_of,
        NEW.command_key, NEW.input)
        IS DISTINCT FROM (OLD.id, OLD.kind, OLD.scope, OLD.label, OLD.reason, OLD.requested_by, OLD.requested_at,
        OLD.retry_of, OLD.command_key, OLD.input) THEN
        RAISE EXCEPTION 'analysis job command is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_analysis_jobs_guard BEFORE UPDATE ON analysis_jobs
    FOR EACH ROW EXECUTE FUNCTION analysis_jobs_guard_update();

-- The job-owned rows V20261014130000 left as plain text until this table existed (DOCUMENT_ANALYSIS.md, "연기한 FK"). Its
-- code never writes them, so they are expected to be NULL; a value that names no job stops the migration with the column
-- named instead of failing on the bare constraint.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM document_analyses d WHERE d.analysis_job_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM analysis_jobs j WHERE j.id = d.analysis_job_id)) THEN
        RAISE EXCEPTION 'document_analyses.analysis_job_id names a job that does not exist';
    END IF;
    IF EXISTS (SELECT 1 FROM ai_executions e WHERE e.analysis_job_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM analysis_jobs j WHERE j.id = e.analysis_job_id)) THEN
        RAISE EXCEPTION 'ai_executions.analysis_job_id names a job that does not exist';
    END IF;
END
$$;

ALTER TABLE document_analyses ADD CONSTRAINT fk_document_analyses_analysis_job FOREIGN KEY (analysis_job_id)
    REFERENCES analysis_jobs (id) ON UPDATE RESTRICT ON DELETE RESTRICT;
ALTER TABLE ai_executions ADD CONSTRAINT fk_ai_executions_analysis_job FOREIGN KEY (analysis_job_id)
    REFERENCES analysis_jobs (id) ON UPDATE RESTRICT ON DELETE RESTRICT;
CREATE INDEX ix_document_analyses_analysis_job ON document_analyses (analysis_job_id) WHERE analysis_job_id IS NOT NULL;
CREATE INDEX ix_ai_executions_analysis_job ON ai_executions (analysis_job_id) WHERE analysis_job_id IS NOT NULL;
