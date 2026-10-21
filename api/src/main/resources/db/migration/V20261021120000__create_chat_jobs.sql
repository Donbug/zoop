-- ERD v6 sections 22, 23 and 36: member conversations, question jobs with their frozen request and verified result, and the
-- read-only tool calls a job makes. Also adds the `ai_executions.chat_job_id` foreign key that the document analysis migration
-- (V20261014130000) deferred to the migration creating `chat_jobs`.
--
-- The application writes these tables through the chat service only. The executor that moves a job from queued to a result
-- (owner token, lease, phase, attempts, tool calls) is a later change; this migration already holds its columns so the stored
-- contract does not change under it.

CREATE TABLE chat_sessions (
    id text PRIMARY KEY,
    member_id text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT fk_chat_sessions_member FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_chat_sessions_id CHECK (id ~ '^[A-Za-z0-9_-]{8,64}$'),
    CONSTRAINT ck_chat_sessions_times CHECK (updated_at >= created_at)
);

CREATE INDEX ix_chat_sessions_member_latest ON chat_sessions (member_id, updated_at DESC, id);

CREATE TABLE chat_jobs (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    seq integer NOT NULL,
    question text NOT NULL,
    request_hash text NOT NULL,
    asked_at timestamptz NOT NULL,
    frozen_context jsonb NOT NULL,
    frozen_selection jsonb NOT NULL,
    context_company_ids text[] NOT NULL DEFAULT '{}',
    graph_version_id text,
    status text NOT NULL,
    phase text,
    outcome text,
    deadline_at timestamptz,
    resolves_job_id text,
    resolves_choice_id text,
    clarification_depth integer NOT NULL DEFAULT 0,
    message_id text,
    result jsonb,
    result_schema_version text,
    failure jsonb,
    route_schema_version text,
    route_summary jsonb,
    runs integer NOT NULL DEFAULT 0,
    attempts jsonb NOT NULL DEFAULT '[]',
    owner_token text,
    lease_until timestamptz,
    recovery_artifact_id text,
    recovery_key text,
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    finished_at timestamptz,
    CONSTRAINT fk_chat_jobs_session FOREIGN KEY (session_id) REFERENCES chat_sessions (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_chat_jobs_graph_version FOREIGN KEY (graph_version_id) REFERENCES graph_versions (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_chat_jobs_resolves FOREIGN KEY (resolves_job_id) REFERENCES chat_jobs (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_chat_jobs_recovery_artifact FOREIGN KEY (recovery_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT uq_chat_jobs_session_seq UNIQUE (session_id, seq),
    CONSTRAINT uq_chat_jobs_message_id UNIQUE (message_id),
    CONSTRAINT uq_chat_jobs_recovery_key UNIQUE (recovery_key),
    CONSTRAINT ck_chat_jobs_id CHECK (id ~ '^[A-Za-z0-9_-]{8,64}$'),
    CONSTRAINT ck_chat_jobs_seq CHECK (seq >= 1),
    CONSTRAINT ck_chat_jobs_question CHECK (char_length(question) BETWEEN 1 AND 4000 AND btrim(question) <> ''),
    CONSTRAINT ck_chat_jobs_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_chat_jobs_frozen_context CHECK (jsonb_typeof(frozen_context) = 'object'),
    CONSTRAINT ck_chat_jobs_frozen_selection CHECK (
        jsonb_typeof(frozen_selection) = 'object'
        AND COALESCE(jsonb_typeof(frozen_selection -> 'contextIds') = 'array', false)
        AND COALESCE(jsonb_typeof(frozen_selection -> 'evidenceIds') = 'array', false)
        AND COALESCE(jsonb_typeof(frozen_selection -> 'evidencePool') = 'array', false)),
    CONSTRAINT ck_chat_jobs_status CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    CONSTRAINT ck_chat_jobs_phase CHECK (
        (status = 'running' OR phase IS NULL)
        AND (phase IS NULL OR phase IN ('planning', 'retrieving', 'writing', 'verifying'))),
    CONSTRAINT ck_chat_jobs_outcome CHECK (
        (outcome IS NOT NULL) = (status = 'completed')
        AND (outcome IS NULL OR outcome IN ('answered', 'clarification', 'guidance', 'insufficient_evidence'))),
    CONSTRAINT ck_chat_jobs_result CHECK (
        (result IS NOT NULL) = (status = 'completed')
        AND (message_id IS NOT NULL) = (status = 'completed')
        AND (result IS NULL OR (jsonb_typeof(result) = 'object' AND result_schema_version IS NOT NULL))),
    CONSTRAINT ck_chat_jobs_failure CHECK (
        (failure IS NOT NULL) = (status = 'failed')
        AND (failure IS NULL OR jsonb_typeof(failure) = 'object')),
    CONSTRAINT ck_chat_jobs_finished CHECK ((finished_at IS NOT NULL) = (status IN ('completed', 'failed', 'cancelled'))),
    CONSTRAINT ck_chat_jobs_route_summary CHECK (route_summary IS NULL OR route_schema_version IS NOT NULL),
    CONSTRAINT ck_chat_jobs_resolves CHECK (resolves_choice_id IS NULL OR resolves_job_id IS NOT NULL),
    CONSTRAINT ck_chat_jobs_clarification_depth CHECK (
        clarification_depth BETWEEN 0 AND 2
        AND (resolves_job_id IS NULL) = (clarification_depth = 0)
        AND (clarification_depth < 2 OR outcome IS DISTINCT FROM 'clarification')),
    CONSTRAINT ck_chat_jobs_runs CHECK (runs BETWEEN 0 AND 3),
    CONSTRAINT ck_chat_jobs_attempts CHECK (jsonb_typeof(attempts) = 'array'),
    CONSTRAINT ck_chat_jobs_ownership CHECK (
        (owner_token IS NULL OR status = 'running') AND (lease_until IS NULL OR status = 'running')),
    CONSTRAINT ck_chat_jobs_times CHECK (updated_at >= created_at AND (finished_at IS NULL OR finished_at >= created_at))
);

-- One queued or running job per conversation: concurrent submissions cannot both be accepted.
CREATE UNIQUE INDEX ux_chat_jobs_session_active ON chat_jobs (session_id) WHERE status IN ('queued', 'running');
CREATE INDEX ix_chat_jobs_resolves ON chat_jobs (resolves_job_id) WHERE resolves_job_id IS NOT NULL;
CREATE INDEX ix_chat_jobs_active ON chat_jobs (status, lease_until) WHERE status IN ('queued', 'running');
CREATE INDEX ix_chat_jobs_graph_version ON chat_jobs (graph_version_id) WHERE graph_version_id IS NOT NULL;

-- What the member asked is fixed at the first acceptance; a completed result and its route summary never change.
CREATE FUNCTION chat_jobs_reject_frozen_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.session_id IS DISTINCT FROM OLD.session_id OR NEW.seq IS DISTINCT FROM OLD.seq
        OR NEW.question IS DISTINCT FROM OLD.question OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.asked_at IS DISTINCT FROM OLD.asked_at OR NEW.frozen_context IS DISTINCT FROM OLD.frozen_context
        OR NEW.frozen_selection IS DISTINCT FROM OLD.frozen_selection
        OR NEW.context_company_ids IS DISTINCT FROM OLD.context_company_ids
        OR NEW.graph_version_id IS DISTINCT FROM OLD.graph_version_id
        OR NEW.resolves_job_id IS DISTINCT FROM OLD.resolves_job_id
        OR NEW.resolves_choice_id IS DISTINCT FROM OLD.resolves_choice_id
        OR NEW.clarification_depth IS DISTINCT FROM OLD.clarification_depth
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'the frozen request of a chat job is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'completed' AND (NEW.status IS DISTINCT FROM OLD.status OR NEW.result IS DISTINCT FROM OLD.result
        OR NEW.outcome IS DISTINCT FROM OLD.outcome OR NEW.message_id IS DISTINCT FROM OLD.message_id
        OR NEW.route_summary IS DISTINCT FROM OLD.route_summary) THEN
        RAISE EXCEPTION 'a completed chat job is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_chat_jobs_frozen BEFORE UPDATE ON chat_jobs
    FOR EACH ROW EXECUTE FUNCTION chat_jobs_reject_frozen_update();

CREATE FUNCTION chat_sessions_reject_owner_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.member_id IS DISTINCT FROM OLD.member_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'the owner of a conversation is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_chat_sessions_owner BEFORE UPDATE ON chat_sessions
    FOR EACH ROW EXECUTE FUNCTION chat_sessions_reject_owner_update();

CREATE TABLE chat_tool_calls (
    id text PRIMARY KEY,
    chat_job_id text NOT NULL,
    attempt_no integer NOT NULL,
    plan_revision integer NOT NULL,
    call_index integer NOT NULL,
    tool_call_id text NOT NULL,
    registry_version text NOT NULL,
    registry_group text NOT NULL,
    capability_id text NOT NULL,
    tool_id text NOT NULL,
    schema_version text NOT NULL,
    input_digest text NOT NULL,
    request_meta jsonb NOT NULL,
    request_artifact_id text,
    response_artifact_id text,
    data_version text,
    evidence_ids text[] NOT NULL DEFAULT '{}',
    truncated boolean,
    next_allowed boolean,
    status text NOT NULL,
    error_code text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    CONSTRAINT fk_chat_tool_calls_job FOREIGN KEY (chat_job_id) REFERENCES chat_jobs (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_chat_tool_calls_request_artifact FOREIGN KEY (request_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_chat_tool_calls_response_artifact FOREIGN KEY (response_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT uq_chat_tool_calls_call_id UNIQUE (chat_job_id, attempt_no, tool_call_id),
    CONSTRAINT uq_chat_tool_calls_call_index UNIQUE (chat_job_id, attempt_no, call_index),
    CONSTRAINT ck_chat_tool_calls_numbers CHECK (attempt_no >= 1 AND plan_revision >= 1 AND call_index >= 0),
    CONSTRAINT ck_chat_tool_calls_status CHECK (status IN ('reserved', 'running', 'succeeded', 'failed', 'cancelled', 'unknown')),
    CONSTRAINT ck_chat_tool_calls_input_digest CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_chat_tool_calls_request_meta CHECK (jsonb_typeof(request_meta) = 'object'),
    CONSTRAINT ck_chat_tool_calls_finished CHECK (
        (finished_at IS NULL) = (status IN ('reserved', 'running'))
        AND (finished_at IS NULL OR finished_at >= started_at))
);

CREATE INDEX ix_chat_tool_calls_tool ON chat_tool_calls (tool_id, started_at);
CREATE INDEX ix_chat_tool_calls_status ON chat_tool_calls (status, started_at);

ALTER TABLE ai_executions ADD CONSTRAINT fk_ai_executions_chat_job FOREIGN KEY (chat_job_id) REFERENCES chat_jobs (id)
    ON UPDATE RESTRICT ON DELETE RESTRICT;
CREATE INDEX ix_ai_executions_chat_job ON ai_executions (chat_job_id) WHERE chat_job_id IS NOT NULL;
