-- ERD v6 sections 26 and 27: the administrator's review targets (a filter projection of the AI source, never the authority)
-- and the append-only history of review decisions (#133).
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
    CONSTRAINT ck_review_decisions_admin CHECK (origin <> 'admin' OR admin_id IS NOT NULL),
    CONSTRAINT ck_review_decisions_revisions CHECK (revision >= 1 AND global_revision >= 1),
    CONSTRAINT ck_review_decisions_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500)
);

CREATE INDEX ix_review_decisions_target ON review_decisions (target_id, revision DESC);
