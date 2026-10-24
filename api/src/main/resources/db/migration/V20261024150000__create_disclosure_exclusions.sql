-- FS081 (WBS 6.6.20): the app's public exclusion store, the overlay DisclosureExclusionReader applies to every read of a version.
--
-- An exclusion keeps already published content of ONE graph version off the public read (rights withdrawn, a mislinked relation).
-- It is scoped per version because the producer may reuse an issue or relation id in a corrected later handoff: a global id set
-- would hide the corrected version too (api/docs/GRAPH_READ_HANDOFF.md, exposure consumption rule 3). Snapshots stay immutable;
-- nothing here changes one.
--
-- History is append-only: one change is one operator command (an `exclude` from an AI exposure report, or an explicit `lift`),
-- with every target it changed. The current state of a target is its latest change. `revision` is the app-wide exclusion counter
-- (DisclosureExclusions.revision), taken as MAX+1 under the shared publication lock and held to the commit, so commit order never
-- inverts it and readers never need the lock. A smaller or empty exposure report never lifts anything (consumption rule 4).

CREATE TABLE disclosure_exclusion_changes (
    revision bigint PRIMARY KEY,
    action text NOT NULL,
    -- exclude: the exposure report's cause; lift: always operator
    cause text NOT NULL,
    -- exclude: SHA-256 of the canonical exposure report the targets came from (the report itself is not stored)
    report_sha256 text,
    reason text NOT NULL,
    operator text NOT NULL,
    changed_at timestamptz NOT NULL,
    CONSTRAINT ck_disclosure_exclusion_changes_revision CHECK (revision >= 1),
    CONSTRAINT ck_disclosure_exclusion_changes_action CHECK (
        (action = 'exclude' AND cause IN ('source-change', 'relation-retraction') AND report_sha256 ~ '^[0-9a-f]{64}$')
        OR (action = 'lift' AND cause = 'operator' AND report_sha256 IS NULL)),
    CONSTRAINT ck_disclosure_exclusion_changes_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
    CONSTRAINT ck_disclosure_exclusion_changes_operator CHECK (operator ~ '^[A-Za-z0-9._@-]{1,100}$')
);

-- One target a change excluded or lifted. Articles are kept by version for the consumers outside the graph read (company
-- documents, S1, briefings: not applied by this slice); the graph read applies issues, relations and evidence.
CREATE TABLE disclosure_exclusion_targets (
    revision bigint NOT NULL,
    graph_version_id text NOT NULL,
    target_kind text NOT NULL,
    target_id text NOT NULL,
    -- article targets only: the article version; '' for every other kind (part of the key)
    article_version text NOT NULL DEFAULT '',
    CONSTRAINT pk_disclosure_exclusion_targets PRIMARY KEY (revision, graph_version_id, target_kind, target_id, article_version),
    CONSTRAINT fk_disclosure_exclusion_targets_change FOREIGN KEY (revision) REFERENCES disclosure_exclusion_changes (revision)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_disclosure_exclusion_targets_version FOREIGN KEY (graph_version_id) REFERENCES graph_versions (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_disclosure_exclusion_targets_kind CHECK (target_kind IN ('issue', 'relation', 'evidence', 'article')),
    CONSTRAINT ck_disclosure_exclusion_targets_id CHECK (target_id ~ '^[A-Za-z0-9._:-]{1,200}$'),
    CONSTRAINT ck_disclosure_exclusion_targets_article CHECK (
        (target_kind = 'article' AND article_version ~ '^[0-9a-f]{64}$') OR (target_kind <> 'article' AND article_version = ''))
);

-- The read is "latest change per target of this version".
CREATE INDEX ix_disclosure_exclusion_targets_version ON disclosure_exclusion_targets
    (graph_version_id, target_kind, target_id, article_version, revision DESC);

-- History: appended to, never rewritten. A target row goes only with its version (graph_versions has no delete guard).
CREATE FUNCTION disclosure_exclusions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'disclosure_exclusion_targets' AND pg_trigger_depth() > 1 THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'disclosure exclusions are append-only' USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_disclosure_exclusion_changes_guard BEFORE UPDATE OR DELETE ON disclosure_exclusion_changes
    FOR EACH ROW EXECUTE FUNCTION disclosure_exclusions_guard();
CREATE TRIGGER tr_disclosure_exclusion_targets_guard BEFORE UPDATE OR DELETE ON disclosure_exclusion_targets
    FOR EACH ROW EXECUTE FUNCTION disclosure_exclusions_guard();
