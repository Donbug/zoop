-- The short values the administrator's candidate list shows (#132, `listAnalysisCandidates`), kept on review_targets so the
-- list never calls the AI service per row and can be searched and paged in SQL.
--
-- Deviation from ERD v6 section 26 (2026-10-26): besides the filter projection (status, company ids, relation types) a target
-- keeps these display values. They are a projection too, never the authority, and are written by the review-target sync from
-- the same S2/S3 results (the S2 content pinned by the analyze-plan unit's hash). Long content (quotes, relation details,
-- verification) is not copied: the candidate detail still reads the AI source again.
--
-- All columns are nullable with no default, so adding them rewrites nothing; a row synced before this migration gets them on
-- its next sync. A relation row and a candidate without an S2 event (a company-to-company relation) have no issue, title,
-- action, target or event time. `companies` holds the source companies ({sourceId, name, role}): AI source ids, not app ids.

ALTER TABLE review_targets
    ADD COLUMN issue_id text,
    ADD COLUMN title text,
    ADD COLUMN action text,
    ADD COLUMN target text,
    ADD COLUMN event_time text,
    ADD COLUMN evidence_count integer,
    ADD COLUMN companies jsonb,
    ADD COLUMN reasons text[],
    -- A relation row whose AI eligibility rests on an operator's final approval (approvalBasis.kind=operator-final-approval):
    -- what tells "approved, waiting for the next handoff" from an automatic pass nobody handed off. Null on candidate rows.
    ADD COLUMN operator_approved boolean,
    ADD CONSTRAINT ck_review_targets_evidence_count CHECK (evidence_count IS NULL OR evidence_count >= 0),
    ADD CONSTRAINT ck_review_targets_companies CHECK (companies IS NULL OR jsonb_typeof(companies) = 'array');

-- The candidate list's order and cursor key: newest sync first.
CREATE INDEX ix_review_targets_candidate_list ON review_targets (updated_at DESC, id DESC)
    WHERE target_type = 'candidate' AND is_current;
