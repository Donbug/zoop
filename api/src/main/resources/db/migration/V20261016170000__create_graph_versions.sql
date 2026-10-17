-- Public graph versions and their activation history (ERD v6 sections 24-25).
-- A version points at one immutable snapshot artifact; the public API reads only that snapshot.
-- admin_id has no FK yet because the admins table does not exist; it is added with admin accounts.

CREATE TABLE graph_versions (
    id text PRIMARY KEY,
    sequence bigint NOT NULL,
    kind text NOT NULL,
    created_at timestamptz NOT NULL,
    published_at timestamptz,
    created_by text NOT NULL,
    reason text,
    source_label text NOT NULL,
    policy_version text,
    issue_count bigint NOT NULL,
    relation_count bigint NOT NULL,
    article_count bigint NOT NULL,
    candidate_count bigint,
    snapshot_artifact_id text NOT NULL REFERENCES artifacts (id),
    review_revision bigint NOT NULL,
    rule_revision bigint,
    graph_db_state jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT false,
    CONSTRAINT uq_graph_versions_sequence UNIQUE (sequence),
    CONSTRAINT ck_graph_versions_id CHECK (id ~ '^[A-Za-z0-9._:-]{1,120}$'),
    CONSTRAINT ck_graph_versions_kind CHECK (kind IN ('fixture', 'snapshot')),
    CONSTRAINT ck_graph_versions_counts CHECK (
        issue_count >= 0 AND relation_count >= 0 AND article_count >= 0
        AND (candidate_count IS NULL OR candidate_count >= 0)),
    CONSTRAINT ck_graph_versions_revisions CHECK (review_revision >= 0 AND (rule_revision IS NULL OR rule_revision >= 0))
);

CREATE UNIQUE INDEX uq_graph_versions_active ON graph_versions (active) WHERE active;

CREATE TABLE graph_activations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id text NOT NULL REFERENCES graph_versions (id),
    previous_version_id text REFERENCES graph_versions (id),
    action text NOT NULL,
    actor_kind text NOT NULL,
    pointer_changed boolean NOT NULL,
    admin_id text,
    admin_email_snapshot text NOT NULL,
    reason text,
    activated_at timestamptz NOT NULL,
    CONSTRAINT ck_graph_activations_action CHECK (action IN ('publish', 'activate', 'seed')),
    CONSTRAINT ck_graph_activations_actor CHECK (
        (actor_kind = 'admin' AND admin_id IS NOT NULL)
        OR (actor_kind = 'system' AND admin_id IS NULL AND admin_email_snapshot = 'system'))
);

CREATE INDEX ix_graph_activations_activated_at ON graph_activations (activated_at DESC, id);
