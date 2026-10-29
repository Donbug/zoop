-- #55 (WBS 6.5.4) graph round composition, step 1: which AI handoff bundles a graph version is composed of, and the bundle's
-- own projection before any publication rule.
--
-- Today every imported version is exactly one bundle (one handoff id); the round automation will assemble one version from the
-- bundles of several rounds. Two facts have to be recorded per bundle for that, and they are recorded from now on:
--   * graph_version_sources: the composition of a version, in order (ordinal). One row per bundle, with the bundle's retained
--     receipt (artifact-receipt-<gv>) and its rule-free projection (below). A version staged before this migration gets its one
--     row backfilled from its source label; it has no rule-free projection (NULL), so it can describe itself but cannot be a base
--     of a composition (the composite import reports such a bundle as dropped, never merges a filtered snapshot).
--   * graph_bundle_snapshot artifacts (artifact-bundle-<gv>, graph_bundle/<gv>.json): the writer's format-3 snapshot of the
--     verified bundle BEFORE the publication rules were applied. A composition re-filters the merged bundles under the rules of
--     its own day, so a rule switched off later shows a bundle's content again; the per-version snapshot (artifact-<gv>) stays
--     the rule-filtered public read exactly as before.
-- The rows belong to their version (CASCADE with it) and are written once: a composition is a fact of the version, never edited.

ALTER TABLE artifacts DROP CONSTRAINT ck_artifacts_kind;
ALTER TABLE artifacts ADD CONSTRAINT ck_artifacts_kind CHECK (kind IN (
    'raw_document', 'extracted_text', 'summary_text', 'analysis_result', 'exact_receipt', 'semantic_receipt',
    'verification_receipt', 'ai_submit', 'ai_call_receipt', 'graph_snapshot', 'graph_bundle_snapshot', 'briefing_input',
    'chat_recovery'));

CREATE TABLE graph_version_sources (
    graph_version_id text NOT NULL,
    ordinal integer NOT NULL,
    handoff_id text NOT NULL,
    receipt_artifact_id text NOT NULL,
    -- NULL only for a version staged before this migration (no rule-free projection was kept then).
    bundle_snapshot_artifact_id text,
    CONSTRAINT pk_graph_version_sources PRIMARY KEY (graph_version_id, ordinal),
    CONSTRAINT uq_graph_version_sources_handoff UNIQUE (graph_version_id, handoff_id),
    CONSTRAINT fk_graph_version_sources_version FOREIGN KEY (graph_version_id) REFERENCES graph_versions (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_graph_version_sources_receipt FOREIGN KEY (receipt_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_graph_version_sources_bundle FOREIGN KEY (bundle_snapshot_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_graph_version_sources_ordinal CHECK (ordinal >= 0),
    CONSTRAINT ck_graph_version_sources_handoff CHECK (handoff_id ~ '^[A-Za-z0-9._:-]{1,200}$')
);

-- "Which versions hold this bundle" (exclusions by bundle, exposure queries) and the composition read, both by index.
CREATE INDEX ix_graph_version_sources_handoff ON graph_version_sources (handoff_id, graph_version_id);

-- Written once with the version. A row leaves only with its version: the CASCADE runs after the version row is gone, which is
-- the one condition under which a delete passes; nothing else may delete or change one.
CREATE FUNCTION graph_version_sources_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM graph_versions WHERE id = OLD.graph_version_id) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'graph version sources are written once' USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_graph_version_sources_guard BEFORE UPDATE OR DELETE ON graph_version_sources
    FOR EACH ROW EXECUTE FUNCTION graph_version_sources_guard();

-- Every version the handoff import staged so far is one bundle: its handoff id is the source label the importer wrote
-- ('graph-handoff:' + handoff id) and its receipt is the artifact the importer registered next to the snapshot. Fixture versions
-- and any other kind have no bundle and get no row.
INSERT INTO graph_version_sources (graph_version_id, ordinal, handoff_id, receipt_artifact_id, bundle_snapshot_artifact_id)
SELECT v.id, 0, substr(v.source_label, length('graph-handoff:') + 1), 'artifact-receipt-' || v.id, NULL
FROM graph_versions v
WHERE v.kind = 'snapshot'
  AND v.source_label LIKE 'graph-handoff:%'
  AND EXISTS (SELECT 1 FROM artifacts a WHERE a.id = 'artifact-receipt-' || v.id AND a.kind = 'verification_receipt');
