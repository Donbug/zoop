-- #55 A-14 (FS081, WBS 6.5.4): an activation carries the public version's unlifted exclusions to the original versions it makes
-- public for the first time.
--
-- Exclusions belong to original (source) versions; a cumulative publication reads those of every source it retains. A new source
-- (a later round's handoff that may reuse an id) does not have the operator's earlier decisions, so the activation, under the
-- publication lock and in its own transaction, appends `exclude` changes with cause `carried` to each new source: every target
-- currently excluded in a source of the version public until then and not yet excluded or lifted in the new source.
-- `base_version_id` names the original version the targets were copied from, never a cumulative publication, so a lift with
-- `laterVersions` on that original also ends the copies. It is no foreign key: the change log refuses UPDATE (append-only
-- triggers), so ON DELETE SET NULL would fail the retention delete of that version; the id string is enough for the audit.
--
-- Forward-only after V20261031170000: the CHECK keeps every cause and receipt meaning the existing rows use
-- (`legacy-operator` and `publication-operator` pin a registered receipt SHA-256 in `report_sha256`) and adds `carried`.

ALTER TABLE disclosure_exclusion_changes ADD COLUMN base_version_id text;

ALTER TABLE disclosure_exclusion_changes DROP CONSTRAINT ck_disclosure_exclusion_changes_action;
ALTER TABLE disclosure_exclusion_changes ADD CONSTRAINT ck_disclosure_exclusion_changes_action CHECK (
    (action = 'exclude' AND cause IN ('source-change', 'relation-retraction', 'legacy-operator', 'publication-operator')
        AND report_sha256 ~ '^[0-9a-f]{64}$' AND base_version_id IS NULL)
    OR (action = 'exclude' AND cause = 'carried' AND report_sha256 IS NULL AND base_version_id IS NOT NULL
        AND base_version_id ~ '^[A-Za-z0-9._:-]{1,120}$')
    OR (action = 'lift' AND cause = 'operator' AND report_sha256 IS NULL AND base_version_id IS NULL));

COMMENT ON COLUMN disclosure_exclusion_changes.base_version_id IS
    'Carried change only: the original version whose current exclusion was copied. Null for operator changes.';
