-- #55 (WBS 6.5.4) graph round automation, step A-2: the app's record of one periodic public-graph round.
--
-- A round is one slot of the AI tick schedule (09:05..17:35 KST, every 30 minutes) carried through the stages the app owns:
-- round-run request → plan → analyze_plan job → freeze request → handoff → import → (auto) activation. The row is the only
-- state the scheduler has: no memory survives a restart, and a second instance (a deploy overlap) takes a row only by lease.
--   * graph_rounds: one row per slot, advanced stage by stage. The AI side keys its own idempotency on the round id, so a failed
--     round is retried under the SAME round id (never a new one) and a round the AI reports as recovered maps onto its row.
--   * graph_round_events: the append-only timeline of every attempt (advanced / waiting / failed / retried / skipped) with the
--     external request id and the codes and digests of the answer. Never a path, a body or a secret. Rows are written once and
--     leave only with their round, which itself is never deleted.
-- The analysis job and the graph version a round produced are foreign keys, so a round can be followed to what it made.

CREATE TABLE graph_rounds (
    round_id text PRIMARY KEY,
    slot_at timestamptz NOT NULL,
    stage text NOT NULL,
    plan_id text,
    plan_digest text,
    analysis_job_id text REFERENCES analysis_jobs (id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    handoff_id text,
    manifest_digest text,
    bundle_digest text,
    -- SET NULL: the retention policy (A-8) prunes old inactive versions; the round row outlives them and then says only that
    -- the version it made is gone.
    graph_version_id text REFERENCES graph_versions (id) ON UPDATE RESTRICT ON DELETE SET NULL,
    activated_version_id text REFERENCES graph_versions (id) ON UPDATE RESTRICT ON DELETE SET NULL,
    activation_note text,
    failure_code text,
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    lease_owner text,
    lease_until timestamptz,
    started_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_graph_rounds_slot UNIQUE (slot_at),
    CONSTRAINT ck_graph_rounds_round_id CHECK (round_id ~ '^round-[0-9]{8}T[0-9]{4}$'),
    CONSTRAINT ck_graph_rounds_stage CHECK (stage IN (
        'scheduled', 'run_requested', 'plan_ready', 'analysis_queued', 'analysis_done', 'freeze_requested',
        'handoff_ready', 'imported', 'skipped', 'failed')),
    CONSTRAINT ck_graph_rounds_failure CHECK ((stage = 'failed') = (failure_code IS NOT NULL)),
    CONSTRAINT ck_graph_rounds_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_graph_rounds_lease CHECK ((lease_owner IS NULL) = (lease_until IS NULL)),
    CONSTRAINT ck_graph_rounds_started_by CHECK (started_by ~ '^(system:scheduler|admin:[A-Za-z0-9._:-]{1,128})$'),
    CONSTRAINT ck_graph_rounds_digests CHECK (
        (manifest_digest IS NULL OR manifest_digest ~ '^[a-f0-9]{64}$')
        AND (bundle_digest IS NULL OR bundle_digest ~ '^[a-f0-9]{64}$')
        AND (plan_digest IS NULL OR plan_digest ~ '^[a-f0-9]{64}$'))
);

-- The scheduler's work list: open rounds oldest first; the admin list: newest first; "newest imported round" for the import
-- order guard (an older round is never imported after a newer one).
CREATE INDEX ix_graph_rounds_open ON graph_rounds (slot_at) WHERE stage NOT IN ('imported', 'skipped', 'failed');
CREATE INDEX ix_graph_rounds_stage_slot ON graph_rounds (stage, slot_at DESC);

CREATE TABLE graph_round_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    round_id text NOT NULL REFERENCES graph_rounds (round_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    at timestamptz NOT NULL,
    stage text NOT NULL,
    outcome text NOT NULL,
    code text,
    request_id text,
    detail jsonb,
    CONSTRAINT ck_graph_round_events_outcome CHECK (outcome IN ('advanced', 'waiting', 'failed', 'retried', 'skipped')),
    CONSTRAINT ck_graph_round_events_code CHECK (code IS NULL OR code ~ '^[a-z0-9_:.-]{1,128}$'),
    CONSTRAINT ck_graph_round_events_request CHECK (request_id IS NULL OR request_id ~ '^[A-Za-z0-9._-]{1,128}$')
);

CREATE INDEX ix_graph_round_events_round ON graph_round_events (round_id, id);

-- Written once: the timeline is the audit history of automatic rounds (manual starts and retries also go to audit_logs).
CREATE FUNCTION graph_round_events_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'graph round events are written once' USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_graph_round_events_guard BEFORE UPDATE OR DELETE ON graph_round_events
    FOR EACH ROW EXECUTE FUNCTION graph_round_events_guard();

-- A round row is kept for good (round-level audit view); only its stage and progress columns change.
CREATE FUNCTION graph_rounds_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'graph rounds are never deleted' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.round_id IS DISTINCT FROM OLD.round_id OR NEW.slot_at IS DISTINCT FROM OLD.slot_at
       OR NEW.started_by IS DISTINCT FROM OLD.started_by OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'graph round identity is written once' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_graph_rounds_guard BEFORE UPDATE OR DELETE ON graph_rounds
    FOR EACH ROW EXECUTE FUNCTION graph_rounds_guard();
