-- The document an analyze-plan unit's S2 job analysed, read by the review-target sync from the S2 result it already checks
-- against the hash the unit's S2 checkpoint recorded (binding.documents[binding.incoming].observation). Two analyses of the same document share it whatever
-- plan, job or snapshot they ran under, which s2_input_digest (it hashes the job id) cannot tell (#132, PR #395).
-- Nullable and filled later: a unit synced before this migration, or whose result does not name the document, stays null and is
-- never treated as a re-analysis.
ALTER TABLE analysis_plan_units
    ADD COLUMN s2_document_id text,
    ADD COLUMN s2_raw_version text,
    ADD COLUMN s2_document_version text;

ALTER TABLE analysis_plan_units ADD CONSTRAINT ck_analysis_plan_unit_document CHECK (
    (s2_document_id IS NULL AND s2_raw_version IS NULL AND s2_document_version IS NULL)
    OR (char_length(s2_document_id) BETWEEN 1 AND 200 AND s2_raw_version ~ '^[a-f0-9]{64}$'
        AND s2_document_version ~ '^[a-f0-9]{64}$'));

CREATE INDEX ix_analysis_plan_units_document
    ON analysis_plan_units (s2_document_id, s2_raw_version, s2_document_version)
    WHERE s2_document_id IS NOT NULL;
