-- ERD v6 sections 26 and 27: the administrator's review targets (a filter projection of the AI source, never the authority),
-- the append-only history of review decisions, and the decision intents the app commits before each AI review call (#133).
-- Triggers keep a target's identity and source version fixed, the decision history append-only and an intent's command fixed.
--
-- Deviation from ERD v6 section 26, agreed with the AI owner (2026-10-22): a target also keeps `source_job_id`, the internal S3
-- job that owns the candidate. AI candidate ids are stable only within one job and its fixed input, so the app key is the job
-- id together with the candidate id, and a decision is sent to that job's review route.
--
-- Revisions: `review_targets.current_revision` is the per-target app revision (0 before any decision), `review_decisions
-- .global_revision` the app-wide one, assigned under the shared publication advisory lock. The AI source revision
-- (`source_revision`) is a different counter and is never written into either.

CREATE TABLE review_targets (
    id text PRIMARY KEY,
    target_type text NOT NULL,
    source_job_id text NOT NULL,
    external_id text NOT NULL,
    source_version text NOT NULL,
    candidate_id text NOT NULL,
    current_revision bigint NOT NULL DEFAULT 0,
    status text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    is_current boolean NOT NULL DEFAULT true,
    company_ids text[] NOT NULL DEFAULT '{}',
    relation_types text[] NOT NULL DEFAULT '{}',
    source_revision text NOT NULL,
    source_updated_at timestamptz,
    verification_artifact_id text,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_review_targets_source UNIQUE (target_type, source_job_id, external_id, source_version),
    CONSTRAINT fk_review_targets_verification FOREIGN KEY (verification_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_review_targets_type CHECK (target_type IN ('candidate', 'relation')),
    CONSTRAINT ck_review_targets_status CHECK (status IN ('ALLOW', 'HOLD', 'REJECT')),
    CONSTRAINT ck_review_targets_revision CHECK (current_revision >= 0),
    CONSTRAINT ck_review_targets_source_revision CHECK (source_revision ~ '^[0-9]+$')
);

-- One current row per candidate and per (candidate, relation); older source versions stay for the decision history.
CREATE UNIQUE INDEX uq_review_targets_current_candidate ON review_targets (source_job_id, candidate_id)
    WHERE target_type = 'candidate' AND is_current;
CREATE UNIQUE INDEX uq_review_targets_current_relation ON review_targets (source_job_id, candidate_id, external_id)
    WHERE target_type = 'relation' AND is_current;
CREATE INDEX ix_review_targets_status ON review_targets (status, updated_at DESC) WHERE is_current;
CREATE INDEX ix_review_targets_company_ids ON review_targets USING gin (company_ids);
CREATE INDEX ix_review_targets_relation_types ON review_targets USING gin (relation_types);

CREATE TABLE review_decisions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    target_id text NOT NULL,
    decision text NOT NULL,
    reason text NOT NULL,
    admin_id text,
    admin_email_snapshot text,
    verification_artifact_id text,
    decided_at timestamptz NOT NULL,
    revision bigint NOT NULL,
    global_revision bigint NOT NULL,
    origin text NOT NULL,
    job_id text,
    CONSTRAINT uq_review_decisions_target_revision UNIQUE (target_id, revision),
    CONSTRAINT uq_review_decisions_global_revision UNIQUE (global_revision),
    CONSTRAINT fk_review_decisions_target FOREIGN KEY (target_id) REFERENCES review_targets (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_review_decisions_admin FOREIGN KEY (admin_id) REFERENCES admins (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_review_decisions_verification FOREIGN KEY (verification_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    -- Only the earlier contract's revalidation link; a current approval or rejection never creates a job.
    CONSTRAINT fk_review_decisions_job FOREIGN KEY (job_id) REFERENCES analysis_jobs (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_review_decisions_decision CHECK (decision IN ('allow', 'reject')),
    CONSTRAINT ck_review_decisions_origin CHECK (origin IN ('admin', 'snapshot-migration')),
    CONSTRAINT ck_review_decisions_admin CHECK (origin <> 'admin' OR (admin_id IS NOT NULL AND admin_email_snapshot IS NOT NULL)),
    CONSTRAINT ck_review_decisions_revisions CHECK (revision >= 1 AND global_revision >= 1),
    CONSTRAINT ck_review_decisions_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500)
);

CREATE INDEX ix_review_decisions_target ON review_decisions (target_id, revision DESC);

-- ERD v6 section 26: a target's identity and source version never change after it is created (the sync refreshes only the
-- projection and source_revision), and its app revision only moves by one, with a decision.
CREATE FUNCTION review_targets_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.target_type, NEW.source_job_id, NEW.external_id, NEW.source_version, NEW.candidate_id)
        IS DISTINCT FROM (OLD.id, OLD.target_type, OLD.source_job_id, OLD.external_id, OLD.source_version, OLD.candidate_id) THEN
        RAISE EXCEPTION 'review target identity is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.current_revision NOT IN (OLD.current_revision, OLD.current_revision + 1) THEN
        RAISE EXCEPTION 'review target revision moves by one' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_review_targets_guard BEFORE UPDATE ON review_targets
    FOR EACH ROW EXECUTE FUNCTION review_targets_guard_update();

-- ERD v6 section 27: the decision history is append-only.
CREATE FUNCTION review_decisions_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'review decisions are append-only' USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_review_decisions_append_only BEFORE UPDATE OR DELETE ON review_decisions
    FOR EACH ROW EXECUTE FUNCTION review_decisions_append_only();

-- The app's durable intent for one decision, committed in its own short transaction BEFORE the AI review call, so a decision
-- the AI source applied can always be settled into review_decisions and audit_logs afterwards (a lost reply, an app stop or a
-- DB failure after the call included). The intent fixes the command: the AI operation id, the target and the request. Its
-- status only moves forward from pending: applied (with the decision row it settled into), refused (the AI source recorded
-- nothing and answered a definite refusal) or blocked (a contract mismatch: only an operation lookup settles it, it is never
-- resent).
CREATE TABLE review_decision_intents (
    id text PRIMARY KEY,
    operation_id text NOT NULL,
    idempotency_record_id text NOT NULL,
    admin_id text NOT NULL,
    admin_email_snapshot text NOT NULL,
    request_id text,
    candidate_id text NOT NULL,
    target_id text NOT NULL,
    source_job_id text NOT NULL,
    relation_candidate_id text NOT NULL,
    decision text NOT NULL,
    reason text NOT NULL,
    expected_revision bigint NOT NULL,
    expected_source_version text NOT NULL,
    expected_source_revision text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    source_code text,
    decision_id bigint,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_review_decision_intents_operation UNIQUE (operation_id),
    CONSTRAINT uq_review_decision_intents_idempotency UNIQUE (idempotency_record_id),
    CONSTRAINT uq_review_decision_intents_decision UNIQUE (decision_id),
    CONSTRAINT fk_review_decision_intents_idempotency FOREIGN KEY (idempotency_record_id) REFERENCES idempotency_records (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_review_decision_intents_admin FOREIGN KEY (admin_id) REFERENCES admins (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_review_decision_intents_target FOREIGN KEY (target_id) REFERENCES review_targets (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_review_decision_intents_decision FOREIGN KEY (decision_id) REFERENCES review_decisions (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_review_decision_intents_operation CHECK (operation_id ~ '^[A-Za-z0-9_.-]{1,120}$'),
    CONSTRAINT ck_review_decision_intents_decision CHECK (decision IN ('allow', 'reject')),
    CONSTRAINT ck_review_decision_intents_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
    CONSTRAINT ck_review_decision_intents_revision CHECK (expected_revision >= 0),
    CONSTRAINT ck_review_decision_intents_source_revision CHECK (expected_source_revision ~ '^[0-9]+$'),
    CONSTRAINT ck_review_decision_intents_status CHECK (status IN ('pending', 'applied', 'refused', 'blocked')),
    CONSTRAINT ck_review_decision_intents_applied CHECK ((status = 'applied') = (decision_id IS NOT NULL)),
    CONSTRAINT ck_review_decision_intents_code CHECK (status NOT IN ('refused', 'blocked') OR source_code IS NOT NULL)
);

-- Intents not settled yet, least recently looked at first (the reconciler's operation lookups).
CREATE INDEX ix_review_decision_intents_open ON review_decision_intents (updated_at, id) WHERE status IN ('pending', 'blocked');

CREATE FUNCTION review_decision_intents_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'review decision intents are kept' USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.id, NEW.operation_id, NEW.idempotency_record_id, NEW.admin_id, NEW.admin_email_snapshot, NEW.request_id,
        NEW.candidate_id, NEW.target_id, NEW.source_job_id, NEW.relation_candidate_id, NEW.decision, NEW.reason,
        NEW.expected_revision, NEW.expected_source_version, NEW.expected_source_revision, NEW.created_at)
        IS DISTINCT FROM (OLD.id, OLD.operation_id, OLD.idempotency_record_id, OLD.admin_id, OLD.admin_email_snapshot,
        OLD.request_id, OLD.candidate_id, OLD.target_id, OLD.source_job_id, OLD.relation_candidate_id, OLD.decision, OLD.reason,
        OLD.expected_revision, OLD.expected_source_version, OLD.expected_source_revision, OLD.created_at) THEN
        RAISE EXCEPTION 'review decision intent command is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    -- Applied and refused are final; a blocked intent can still be settled as applied by an operation lookup.
    IF OLD.status IN ('applied', 'refused') AND NEW IS DISTINCT FROM OLD
        OR OLD.status = 'blocked' AND NEW.status NOT IN ('blocked', 'applied') THEN
        RAISE EXCEPTION 'review decision intent is settled' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_review_decision_intents_guard BEFORE UPDATE OR DELETE ON review_decision_intents
    FOR EACH ROW EXECUTE FUNCTION review_decision_intents_guard();
