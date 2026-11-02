-- Automatic preparations of the round path (#55 PR-P3): one row per attempt the writer's round scheduler makes after a new import.
-- The request and decision bytes commit before the composition runs, so an attempt whose outcome is unknown (the process stopped,
-- or the composer answered outcome_unknown) is recovered with exactly those bytes: a recovery is a new row naming the attempt it
-- recovers (recovery_of). trigger_sequence is the newest import (graph_versions.sequence of a single-source snapshot) the attempt
-- answered, so the scheduler prepares once per new import. round_id names the newest imported round for reading only (no FK: the
-- round tables are cleaned on their own in tests and nothing here depends on the row). The result columns are written at most
-- once, from NULL; nothing else changes and no row is deleted.
CREATE TABLE graph_publication_preparations (
    id bigserial PRIMARY KEY,
    round_id text,
    trigger_sequence bigint NOT NULL,
    recovery_of bigint REFERENCES graph_publication_preparations (id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    active_version_id text,
    request bytea CHECK (request IS NULL OR octet_length(request) BETWEEN 1 AND 65536),
    request_sha256 text CHECK (request_sha256 IS NULL OR request_sha256 ~ '^[a-f0-9]{64}$'),
    decisions bytea CHECK (decisions IS NULL OR octet_length(decisions) BETWEEN 1 AND 4000000),
    decisions_sha256 text CHECK (decisions_sha256 IS NULL OR decisions_sha256 ~ '^[a-f0-9]{64}$'),
    status text CHECK (status IS NULL OR status IN ('succeeded', 'failed')),
    code text CHECK (code IS NULL OR code ~ '^[a-z0-9_:.-]{1,128}$'),
    graph_version_id text,
    result jsonb,
    completed_at timestamptz,
    CONSTRAINT ck_graph_publication_preparations_inputs CHECK (
        (request IS NULL) = (request_sha256 IS NULL) AND (request IS NULL) = (decisions IS NULL)
        AND (decisions IS NULL) = (decisions_sha256 IS NULL)),
    CONSTRAINT ck_graph_publication_preparations_recovery CHECK (recovery_of IS NULL OR request IS NOT NULL),
    CONSTRAINT ck_graph_publication_preparations_result CHECK (
        (status IS NULL) = (result IS NULL) AND (status IS NULL) = (completed_at IS NULL)
        AND (status IS NULL OR code IS NOT NULL))
);
CREATE INDEX ix_graph_publication_preparations_recovery ON graph_publication_preparations (recovery_of);
CREATE INDEX ix_graph_publication_preparations_trigger ON graph_publication_preparations (trigger_sequence);

CREATE FUNCTION graph_publication_preparations_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'graph_publication_preparations rows are permanent';
    END IF;
    IF OLD.status IS NOT NULL
        OR NEW.id <> OLD.id OR NEW.round_id IS DISTINCT FROM OLD.round_id
        OR NEW.trigger_sequence <> OLD.trigger_sequence OR NEW.recovery_of IS DISTINCT FROM OLD.recovery_of
        OR NEW.created_at <> OLD.created_at OR NEW.active_version_id IS DISTINCT FROM OLD.active_version_id
        OR NEW.request IS DISTINCT FROM OLD.request OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256
        OR NEW.decisions IS DISTINCT FROM OLD.decisions OR NEW.decisions_sha256 IS DISTINCT FROM OLD.decisions_sha256 THEN
        RAISE EXCEPTION 'graph_publication_preparations: only an unwritten result may be written, once';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_graph_publication_preparations_guard BEFORE UPDATE OR DELETE ON graph_publication_preparations
    FOR EACH ROW EXECUTE FUNCTION graph_publication_preparations_guard();
