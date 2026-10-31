CREATE TABLE graph_publications (
    version_id text PRIMARY KEY REFERENCES graph_versions(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    publication_id text NOT NULL UNIQUE CHECK (publication_id ~ '^publication:[0-9a-f]{64}$'),
    composition_digest text NOT NULL CHECK (composition_digest ~ '^[0-9a-f]{64}$'),
    base_version_id text REFERENCES graph_versions(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    expected_active_version_id text REFERENCES graph_versions(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_graph_publication_base CHECK (base_version_id IS NULL OR base_version_id = expected_active_version_id),
    CONSTRAINT ck_graph_publication_identity CHECK (publication_id = 'publication:' || composition_digest)
);

CREATE TABLE graph_publication_inputs (
    version_id text NOT NULL REFERENCES graph_publications(version_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0 AND ordinal < 20),
    source_version_id text NOT NULL REFERENCES graph_versions(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    PRIMARY KEY (version_id, ordinal),
    UNIQUE (version_id, source_version_id)
);

CREATE FUNCTION graph_publication_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'graph publication provenance is immutable' USING ERRCODE = 'restrict_violation';
END
$$;
CREATE TRIGGER tr_graph_publications_immutable BEFORE UPDATE OR DELETE ON graph_publications
    FOR EACH ROW EXECUTE FUNCTION graph_publication_immutable();
CREATE TRIGGER tr_graph_publication_inputs_immutable BEFORE UPDATE OR DELETE ON graph_publication_inputs
    FOR EACH ROW EXECUTE FUNCTION graph_publication_immutable();

ALTER TABLE disclosure_exclusion_changes DROP CONSTRAINT ck_disclosure_exclusion_changes_action;
ALTER TABLE disclosure_exclusion_changes ADD CONSTRAINT ck_disclosure_exclusion_changes_action CHECK (
    (action = 'exclude' AND cause IN ('source-change', 'relation-retraction', 'legacy-operator', 'publication-operator')
        AND report_sha256 ~ '^[0-9a-f]{64}$')
    OR (action = 'lift' AND cause = 'operator' AND report_sha256 IS NULL));

COMMENT ON COLUMN graph_version_sources.bundle_snapshot_artifact_id IS
    'Immutable rule-free projection. A null or unavailable original projection refuses composition as basis_unavailable.';
