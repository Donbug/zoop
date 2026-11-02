ALTER TABLE disclosure_exclusion_changes
    DROP CONSTRAINT ck_disclosure_exclusion_changes_action;

ALTER TABLE disclosure_exclusion_changes
    ADD CONSTRAINT ck_disclosure_exclusion_changes_action CHECK (
        (action = 'exclude' AND cause IN ('source-change', 'relation-retraction', 'legacy-operator')
            AND report_sha256 ~ '^[0-9a-f]{64}$')
        OR (action = 'lift' AND cause = 'operator' AND report_sha256 IS NULL));

COMMENT ON COLUMN disclosure_exclusion_changes.report_sha256 IS
    'Native exclusion: canonical exposure report SHA-256. Legacy-operator exclusion: registered immutable legacy receipt SHA-256.';
