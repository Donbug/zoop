-- ERD v6 sections 17, 18 and 32: independently readable evidence, per-stage document analyses and AI call executions.
-- This is the application side of an operator-run document analysis (api/docs/DOCUMENT_ANALYSIS.md); it builds on the
-- `artifacts`, `articles` and `article_versions` tables of the document registry and on `companies`.
--
-- Deliberately NOT part of it: `analysis_jobs`, chat jobs and briefing attempts do not exist yet and belong to other owners.
-- `document_analyses.analysis_job_id`, `ai_executions.chat_job_id`, `.briefing_attempt_id` and `.analysis_job_id` are therefore
-- plain text columns here; their foreign keys are added by the migration that creates the referenced table (the same
-- precedent as `briefing_rounds.graph_version_id`). Nothing in this migration writes those columns.

CREATE TABLE document_analyses (
    id text PRIMARY KEY,
    article_id text NOT NULL,
    article_version text NOT NULL,
    stage text NOT NULL,
    company_id text,
    request_no bigint NOT NULL,
    status text NOT NULL,
    reason text,
    result_version text,
    result jsonb,
    summary_text_artifact_id text,
    result_artifact_id text,
    exact_receipt_id text,
    semantic_receipt_id text,
    grant_reference text,
    grant_revision text,
    grant_checked_at timestamptz,
    revoked_at timestamptz,
    model text,
    prompt_version text,
    reasoning_effort text,
    analysis_job_id text,
    ai_job_id text,
    owner_token text,
    lease_until timestamptz,
    created_at timestamptz NOT NULL,
    produced_at timestamptz,
    updated_at timestamptz NOT NULL,
    CONSTRAINT fk_document_analyses_version FOREIGN KEY (article_id, article_version)
        REFERENCES article_versions (article_id, version) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_document_analyses_company FOREIGN KEY (company_id) REFERENCES companies (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_document_analyses_summary_text FOREIGN KEY (summary_text_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_document_analyses_result_artifact FOREIGN KEY (result_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_document_analyses_exact_receipt FOREIGN KEY (exact_receipt_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_document_analyses_semantic_receipt FOREIGN KEY (semantic_receipt_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT uq_document_analyses_ai_job_id UNIQUE (ai_job_id),
    CONSTRAINT ck_document_analyses_stage CHECK (stage IN ('summary', 'sentiment')),
    CONSTRAINT ck_document_analyses_status CHECK (status IN ('not_requested', 'pending', 'failed', 'withheld', 'available')),
    CONSTRAINT ck_document_analyses_company_scope CHECK ((stage = 'summary') = (company_id IS NULL)),
    CONSTRAINT ck_document_analyses_request_no CHECK (request_no >= 1),
    CONSTRAINT ck_document_analyses_reason CHECK (
        (status IN ('pending', 'available') AND reason IS NULL)
        OR (status IN ('failed', 'withheld') AND reason IS NOT NULL AND reason ~ '^[A-Za-z0-9_.:-]{1,80}$')
        OR status = 'not_requested'),
    CONSTRAINT ck_document_analyses_result CHECK (
        num_nonnulls(result, result_version, result_artifact_id, exact_receipt_id, semantic_receipt_id, produced_at)
            = CASE WHEN status = 'available' THEN 6 ELSE 0 END),
    CONSTRAINT ck_document_analyses_result_object CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    CONSTRAINT ck_document_analyses_ai_job CHECK (
        (status = 'not_requested' OR ai_job_id IS NOT NULL)
        AND (ai_job_id IS NULL OR ai_job_id ~ '^[A-Za-z0-9_.-]{1,120}$')),
    CONSTRAINT ck_document_analyses_grant CHECK (
        num_nonnulls(grant_reference, grant_revision, grant_checked_at) = 3
        OR (status = 'not_requested' AND num_nonnulls(grant_reference, grant_revision, grant_checked_at) = 0)),
    CONSTRAINT ck_document_analyses_lease CHECK ((owner_token IS NULL) = (lease_until IS NULL)),
    CONSTRAINT ck_document_analyses_model CHECK (status <> 'available' OR (model IS NOT NULL AND prompt_version IS NOT NULL))
);

-- At most one pending request per ERD scope; the document row lock serialises writers and these indexes defend the race.
CREATE UNIQUE INDEX ux_document_analyses_pending
    ON document_analyses (article_id, article_version, stage) WHERE company_id IS NULL AND status = 'pending';
CREATE UNIQUE INDEX ux_document_analyses_pending_company
    ON document_analyses (article_id, article_version, stage, company_id) WHERE company_id IS NOT NULL AND status = 'pending';
CREATE UNIQUE INDEX ux_document_analyses_request_no
    ON document_analyses (article_id, article_version, stage, request_no) WHERE company_id IS NULL;
CREATE UNIQUE INDEX ux_document_analyses_request_no_company
    ON document_analyses (article_id, article_version, stage, company_id, request_no) WHERE company_id IS NOT NULL;
CREATE UNIQUE INDEX ux_document_analyses_result_version ON document_analyses (result_version) WHERE result_version IS NOT NULL;
CREATE INDEX ix_document_analyses_latest ON document_analyses (article_id, article_version, stage, request_no DESC);
CREATE INDEX ix_document_analyses_company ON document_analyses (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX ix_document_analyses_summary_text ON document_analyses (summary_text_artifact_id) WHERE summary_text_artifact_id IS NOT NULL;
CREATE INDEX ix_document_analyses_result_artifact ON document_analyses (result_artifact_id) WHERE result_artifact_id IS NOT NULL;
CREATE INDEX ix_document_analyses_exact_receipt ON document_analyses (exact_receipt_id) WHERE exact_receipt_id IS NOT NULL;
CREATE INDEX ix_document_analyses_semantic_receipt ON document_analyses (semantic_receipt_id) WHERE semantic_receipt_id IS NOT NULL;

-- ERD: the identity of a request never changes; ai_job_id, analysis_job_id and the grant snapshot are fixed once issued;
-- a pending request moves to exactly one terminal status once, and a terminal row only records a later revocation
-- observation (`revoked_at`, which is history and not current authority) and its own `updated_at`.
CREATE FUNCTION document_analyses_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.article_id, NEW.article_version, NEW.stage, NEW.company_id, NEW.request_no, NEW.created_at)
        IS DISTINCT FROM (OLD.id, OLD.article_id, OLD.article_version, OLD.stage, OLD.company_id, OLD.request_no, OLD.created_at) THEN
        RAISE EXCEPTION 'document analysis identity is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF (OLD.ai_job_id IS NOT NULL AND NEW.ai_job_id IS DISTINCT FROM OLD.ai_job_id)
        OR (OLD.analysis_job_id IS NOT NULL AND NEW.analysis_job_id IS DISTINCT FROM OLD.analysis_job_id)
        OR (OLD.grant_reference IS NOT NULL
            AND (NEW.grant_reference, NEW.grant_revision, NEW.grant_checked_at)
                IS DISTINCT FROM (OLD.grant_reference, OLD.grant_revision, OLD.grant_checked_at)) THEN
        RAISE EXCEPTION 'document analysis job and grant snapshot are fixed once issued' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status IN ('failed', 'withheld', 'available') THEN
        IF (to_jsonb(NEW) - 'revoked_at' - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at' - 'updated_at') THEN
            RAISE EXCEPTION 'a finished document analysis is immutable' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'not_requested' AND NEW.status = 'pending')
        OR (OLD.status = 'pending' AND NEW.status IN ('failed', 'withheld', 'available'))) THEN
        RAISE EXCEPTION 'invalid document analysis status transition' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_document_analyses_guard BEFORE UPDATE ON document_analyses
    FOR EACH ROW EXECUTE FUNCTION document_analyses_guard_update();

-- ERD section 17. Evidence is immutable once stored (it is referenced by results and by getEvidence).
CREATE TABLE evidence (
    id text PRIMARY KEY,
    article_id text NOT NULL,
    article_version text NOT NULL,
    text_artifact_id text NOT NULL,
    summary_analysis_id text,
    quote text NOT NULL,
    start_offset bigint NOT NULL,
    end_offset bigint NOT NULL,
    offset_unit text NOT NULL,
    input_kind text NOT NULL,
    raw_locator_ids jsonb NOT NULL,
    quote_verified boolean,
    verification_artifact_id text,
    verified_at timestamptz,
    created_at timestamptz NOT NULL,
    CONSTRAINT fk_evidence_version FOREIGN KEY (article_id, article_version)
        REFERENCES article_versions (article_id, version) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_evidence_text_artifact FOREIGN KEY (text_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_evidence_summary_analysis FOREIGN KEY (summary_analysis_id) REFERENCES document_analyses (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_evidence_verification_artifact FOREIGN KEY (verification_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_evidence_offsets CHECK (start_offset >= 0 AND start_offset < end_offset),
    CONSTRAINT ck_evidence_offset_unit CHECK (offset_unit = 'unicode_code_point'),
    CONSTRAINT ck_evidence_input_kind CHECK (input_kind IN ('body', 'summary')),
    CONSTRAINT ck_evidence_summary_link CHECK ((input_kind = 'summary') = (summary_analysis_id IS NOT NULL)),
    -- char_length counts code points in a UTF-8 database, which is the unit of the offsets.
    CONSTRAINT ck_evidence_quote CHECK (char_length(quote) = end_offset - start_offset),
    CONSTRAINT ck_evidence_locators CHECK (
        CASE WHEN jsonb_typeof(raw_locator_ids) = 'array'
            THEN jsonb_array_length(raw_locator_ids) >= 1
                AND NOT jsonb_path_exists(raw_locator_ids, '$[*] ? (@.type() != "string")')
            ELSE false END),
    CONSTRAINT ck_evidence_verification CHECK (
        quote_verified IS NOT TRUE OR (verification_artifact_id IS NOT NULL AND verified_at IS NOT NULL))
);

CREATE INDEX ix_evidence_version ON evidence (article_id, article_version);
CREATE INDEX ix_evidence_text_artifact ON evidence (text_artifact_id);
CREATE INDEX ix_evidence_summary_analysis ON evidence (summary_analysis_id) WHERE summary_analysis_id IS NOT NULL;
CREATE INDEX ix_evidence_verification_artifact ON evidence (verification_artifact_id) WHERE verification_artifact_id IS NOT NULL;

CREATE TRIGGER tr_evidence_immutable BEFORE UPDATE ON evidence
    FOR EACH ROW EXECUTE FUNCTION document_registry_reject_update();

-- ERD section 32. One row per AI attempt receipt (and, later, per app-side replay/save-only record).
CREATE TABLE ai_executions (
    id text PRIMARY KEY,
    feature text NOT NULL,
    execution_mode text NOT NULL,
    status text NOT NULL,
    chat_job_id text,
    briefing_attempt_id text,
    analysis_job_id text,
    document_analysis_id text,
    ai_job_id text,
    ai_attempt_id text,
    stage text,
    receipt_artifact_id text,
    grant_id text,
    grant_revision text,
    grant_checked_at timestamptz,
    grant_scope jsonb,
    attempt_no integer,
    provider text,
    model text,
    prompt_version text,
    reasoning_effort text,
    input_tokens bigint,
    output_tokens bigint,
    estimated_cost numeric,
    actual_cost numeric,
    currency text,
    error_code text,
    error_message text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    CONSTRAINT fk_ai_executions_document_analysis FOREIGN KEY (document_analysis_id) REFERENCES document_analyses (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_ai_executions_receipt_artifact FOREIGN KEY (receipt_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_ai_executions_feature CHECK (feature IN ('chatbot', 'news-analysis', 'briefing', 'document-sentiment', 'briefing-outlook')),
    CONSTRAINT ck_ai_executions_mode CHECK (execution_mode IN ('live', 'replay', 'save_only')),
    CONSTRAINT ck_ai_executions_status CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled', 'unknown')),
    CONSTRAINT ck_ai_executions_owner CHECK (num_nonnulls(chat_job_id, briefing_attempt_id, analysis_job_id, document_analysis_id) >= 1),
    CONSTRAINT ck_ai_executions_single_owner CHECK (num_nonnulls(chat_job_id, briefing_attempt_id, analysis_job_id) <= 1),
    CONSTRAINT ck_ai_executions_attempt_pair CHECK ((ai_job_id IS NULL) = (ai_attempt_id IS NULL)),
    CONSTRAINT ck_ai_executions_attempt_no CHECK (attempt_no IS NULL OR attempt_no >= 1),
    CONSTRAINT ck_ai_executions_amounts CHECK (
        (input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0)
        AND (estimated_cost IS NULL OR estimated_cost >= 0) AND (actual_cost IS NULL OR actual_cost >= 0)),
    CONSTRAINT ck_ai_executions_grant_scope CHECK (
        grant_scope IS NULL OR (
            COALESCE(jsonb_typeof(grant_scope) = 'object', false)
            AND COALESCE(jsonb_typeof(grant_scope -> 'sourceId') = 'string', false)
            AND COALESCE(jsonb_typeof(grant_scope -> 'requiredOperations') = 'array', false)
            AND COALESCE(jsonb_typeof(grant_scope -> 'requiredPurposes') = 'array', false)
            AND COALESCE(jsonb_typeof(grant_scope -> 'requiredRecipients') = 'array', false)))
);

CREATE UNIQUE INDEX ux_ai_executions_attempt ON ai_executions (ai_job_id, ai_attempt_id)
    WHERE ai_job_id IS NOT NULL AND ai_attempt_id IS NOT NULL;
CREATE INDEX ix_ai_executions_feature ON ai_executions (feature, started_at);
CREATE INDEX ix_ai_executions_status ON ai_executions (status, started_at);
CREATE INDEX ix_ai_executions_document_analysis ON ai_executions (document_analysis_id) WHERE document_analysis_id IS NOT NULL;
CREATE INDEX ix_ai_executions_receipt_artifact ON ai_executions (receipt_artifact_id) WHERE receipt_artifact_id IS NOT NULL;

-- ERD section 32: when a document analysis is the execution's only owner, the AI job of the receipt must be the analysis's
-- own `ai_job_id`. (A receipt of a cache-reused result belongs to the row that created it, not to the requesting row.)
CREATE FUNCTION ai_executions_check_document_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.document_analysis_id IS NOT NULL AND NEW.ai_job_id IS NOT NULL
        AND num_nonnulls(NEW.chat_job_id, NEW.briefing_attempt_id, NEW.analysis_job_id) = 0
        AND NOT EXISTS (SELECT 1 FROM document_analyses d WHERE d.id = NEW.document_analysis_id AND d.ai_job_id = NEW.ai_job_id) THEN
        RAISE EXCEPTION 'the AI job of a document analysis execution must be the analysis ai_job_id' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_ai_executions_document_owner BEFORE INSERT ON ai_executions
    FOR EACH ROW EXECUTE FUNCTION ai_executions_check_document_owner();

-- A row written from an AI call receipt is occurrence history: it is never rewritten (usage is counted from it once).
CREATE FUNCTION ai_executions_reject_receipt_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.receipt_artifact_id IS NOT NULL THEN
        RAISE EXCEPTION 'a receipt-backed AI execution is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_ai_executions_receipt_immutable BEFORE UPDATE ON ai_executions
    FOR EACH ROW EXECUTE FUNCTION ai_executions_reject_receipt_update();
