-- FS070-02. Operator-admitted input, not client supplied model commands or prompts.
CREATE TABLE briefing_reprocess_inputs (
    round_id text PRIMARY KEY REFERENCES briefing_rounds(id) ON DELETE RESTRICT,
    input_artifact_id text NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,
    operation text NOT NULL CHECK (operation IN ('generation','save_only_generation')),
    max_calls integer NOT NULL CHECK (max_calls BETWEEN 0 AND 16),
    authorization_ref text NOT NULL CHECK (btrim(authorization_ref)<>''),
    enabled boolean NOT NULL DEFAULT true,
    CHECK (operation<>'save_only_generation' OR max_calls=0)
);
CREATE TABLE briefing_reprocess_jobs (
    id text PRIMARY KEY,
    round_id text NOT NULL REFERENCES briefing_rounds(id) ON DELETE RESTRICT,
    attempt_id text NOT NULL UNIQUE REFERENCES briefing_attempts(id) ON DELETE RESTRICT,
    admin_id text NOT NULL REFERENCES admins(id) ON DELETE RESTRICT,
    request_key text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 200),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 500),
    operation text NOT NULL CHECK (operation IN ('generation','save_only_generation')),
    input_artifact_id text NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,
    max_calls integer NOT NULL CHECK (max_calls BETWEEN 0 AND 16),
    authorization_ref text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','running','completed','failed')),
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    failure_code text,
    UNIQUE(admin_id,round_id,request_key),
    CHECK ((finished_at IS NOT NULL)=(status IN ('completed','failed')))
);
CREATE UNIQUE INDEX uq_briefing_reprocess_active ON briefing_reprocess_jobs(round_id) WHERE status IN ('queued','running');
CREATE INDEX ix_briefing_reprocess_queue ON briefing_reprocess_jobs(created_at) WHERE status='queued';
