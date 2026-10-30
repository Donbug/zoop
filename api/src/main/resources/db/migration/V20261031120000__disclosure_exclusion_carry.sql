-- #55 A-14 (FS081, WBS 6.5.4): an activation carries the active version's unlifted exclusions to the version it makes public.
--
-- Exclusions are per version (a corrected later handoff may reuse an id). With a round every 30 minutes, an exclusion the
-- operator applied to the public version would end the moment the next round's version is activated. So the activation, under
-- the publication lock and in its own transaction, appends one `exclude` change with cause `carried` to the version it activates:
-- every target currently excluded in the version that was public until then and not yet excluded in the new one. A target is
-- carried whether or not the new snapshot holds its id (a lift is still the only end of an exclusion, exposure consumption rule 4;
-- an id absent from the snapshot filters nothing). `base_version_id` names the version the targets were carried from. It is no
-- foreign key: the change log refuses UPDATE (append-only triggers), so ON DELETE SET NULL would fail the retention delete of
-- that version; the id string is enough for the audit.

ALTER TABLE disclosure_exclusion_changes ADD COLUMN base_version_id text;

ALTER TABLE disclosure_exclusion_changes DROP CONSTRAINT ck_disclosure_exclusion_changes_action;
ALTER TABLE disclosure_exclusion_changes ADD CONSTRAINT ck_disclosure_exclusion_changes_action CHECK (
    (action = 'exclude' AND cause IN ('source-change', 'relation-retraction') AND report_sha256 ~ '^[0-9a-f]{64}$'
        AND base_version_id IS NULL)
    OR (action = 'exclude' AND cause = 'carried' AND report_sha256 IS NULL AND base_version_id IS NOT NULL
        AND base_version_id ~ '^[A-Za-z0-9._:-]{1,120}$')
    OR (action = 'lift' AND cause = 'operator' AND report_sha256 IS NULL AND base_version_id IS NULL));
