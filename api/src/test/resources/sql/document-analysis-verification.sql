-- Run against an isolated DB after Flyway (psql -X -v ON_ERROR_STOP=1); every fixture row is rolled back, so the script can
-- also run on the database an analysis smoke just used: fixture ids are prefixed proof-/pa-/da-/job-/ev-/aix-, the synthetic
-- companies use the exchange_code 'PROOF' (never a real exchange), and no assertion counts rows it did not create. It proves
-- the ERD v6 section 17, 18 and 32 constraints the migration V20261014130000 creates: CHECKs, the partial unique indexes
-- that serialise pending requests, the foreign keys, and the immutability triggers. It depends on the document registry
-- (artifacts, articles, article_versions) and on companies.
BEGIN;

DO $$
BEGIN
    IF (SELECT count(*) FROM flyway_schema_history WHERE version = '20261014130000' AND success) <> 1 THEN
        RAISE EXCEPTION 'document analysis migration is not recorded as applied';
    END IF;
    IF (SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema() AND indexname IN
        ('ux_document_analyses_pending', 'ux_document_analyses_pending_company', 'ux_document_analyses_request_no',
         'ux_document_analyses_request_no_company', 'ux_document_analyses_result_version', 'ix_document_analyses_latest',
         'ux_ai_executions_attempt', 'ix_ai_executions_feature', 'ix_ai_executions_status', 'ix_evidence_version')) <> 10 THEN
        RAISE EXCEPTION 'document analysis indexes are missing';
    END IF;
    IF (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN
        ('tr_document_analyses_guard', 'tr_evidence_immutable', 'tr_ai_executions_document_owner',
         'tr_ai_executions_receipt_immutable')) <> 4 THEN
        RAISE EXCEPTION 'document analysis triggers are missing';
    END IF;
END $$;

-- ---------------------------------------------------------------------------------------------------------------------
-- fixtures: two catalog companies, artifacts of every kind this app writes, one article with two versions
-- ---------------------------------------------------------------------------------------------------------------------
INSERT INTO companies (id, ticker, exchange_code, name, market) VALUES
    ('proof-co-a', 'PROOF-A', 'PROOF', '증명 알파', 'SYNTHETIC'),
    ('proof-co-b', 'PROOF-B', 'PROOF', '증명 베타', 'SYNTHETIC');

INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at) VALUES
    ('pa-text', 'extracted_text', 'artifact-root:extracted_text/pa.txt', repeat('a', 64), 10, 'text/plain; charset=utf-8', now()),
    ('pa-result-1', 'analysis_result', 'artifact-root:analysis_result/r1.json', repeat('1', 64), 10, 'application/json', now()),
    ('pa-result-2', 'analysis_result', 'artifact-root:analysis_result/r2.json', repeat('2', 64), 10, 'application/json', now()),
    ('pa-sem-1', 'semantic_receipt', 'artifact-root:semantic_receipt/s1.json', repeat('3', 64), 10, 'application/json', now()),
    ('pa-sem-2', 'semantic_receipt', 'artifact-root:semantic_receipt/s2.json', repeat('4', 64), 10, 'application/json', now()),
    ('pa-exact-1', 'exact_receipt', 'artifact-root:exact_receipt/e1.json', repeat('5', 64), 10, 'application/json', now()),
    ('pa-exact-2', 'exact_receipt', 'artifact-root:exact_receipt/e2.json', repeat('6', 64), 10, 'application/json', now()),
    ('pa-rcpt-1', 'ai_call_receipt', 'artifact-root:ai_call_receipt/c1.json', repeat('7', 64), 10, 'application/json', now()),
    ('pa-rcpt-2', 'ai_call_receipt', 'artifact-root:ai_call_receipt/c2.json', repeat('8', 64), 10, 'application/json', now()),
    ('pa-rcpt-3', 'ai_call_receipt', 'artifact-root:ai_call_receipt/c3.json', repeat('9', 64), 10, 'application/json', now());

INSERT INTO articles (id, kind, provider, access_status, created_at) VALUES
    ('pa-article', 'news', 'proof-source', 'available', now());
INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at) VALUES
    ('pa-article', 'v1', 'unknown', 'pa-text', now()),
    ('pa-article', 'v2', 'unknown', 'pa-text', now());

-- A pending request exactly as the reserving transaction writes it.
CREATE FUNCTION pg_temp.pending(p_id text, p_stage text, p_company text, p_no bigint, p_job text, p_version text DEFAULT 'v1')
RETURNS void LANGUAGE sql AS $$
    INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                   grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
    VALUES (p_id, 'pa-article', p_version, p_stage, p_company, p_no, 'pending', 'grant-1', 'rev-1', now(), p_job, now(), now())
$$;

-- The result of a finished request exactly as the settling transaction writes it.
CREATE FUNCTION pg_temp.available(p_id text, p_version text, p_result text, p_exact text, p_semantic text)
RETURNS void LANGUAGE sql AS $$
    UPDATE document_analyses
    SET status = 'available', result = '{"schemaVersion":"zoop-ai-s1-1"}'::jsonb, result_version = p_version,
        result_artifact_id = p_result, exact_receipt_id = p_exact, semantic_receipt_id = p_semantic, produced_at = now(),
        model = 'authored-synthetic', prompt_version = 'prompt-1', updated_at = now()
    WHERE id = p_id
$$;

DO $$
DECLARE
    changed integer;
BEGIN
    PERFORM pg_temp.pending('da-s1', 'summary', NULL, 1, 'job-s1');
    PERFORM pg_temp.pending('da-t1', 'sentiment', 'proof-co-a', 1, 'job-t1');
    -- A sentiment of another company and a summary of another version are separate scopes: each may be pending at once.
    PERFORM pg_temp.pending('da-t2', 'sentiment', 'proof-co-b', 1, 'job-t2');
    PERFORM pg_temp.pending('da-s-v2', 'summary', NULL, 1, 'job-s-v2', 'v2');
    IF (SELECT count(*) FROM document_analyses WHERE article_id = 'pa-article' AND status = 'pending') <> 4 THEN
        RAISE EXCEPTION 'independent pending scopes were not all accepted';
    END IF;

    -- ---------------------------------------------------------------- document_analyses: CHECKs
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                       grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-stage', 'pa-article', 'v1', 'chat', NULL, 9, 'pending', 'g', 'r', now(), 'job-bad-stage', now(), now());
        RAISE EXCEPTION 'unknown stage was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('bad-summary-company', 'summary', 'proof-co-a', 9, 'job-bad-1');
        RAISE EXCEPTION 'a summary with a company was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('bad-sentiment-nocompany', 'sentiment', NULL, 9, 'job-bad-2');
        RAISE EXCEPTION 'a sentiment without a company was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('bad-request-no', 'summary', NULL, 0, 'job-bad-3', 'v2');
        RAISE EXCEPTION 'request_no 0 was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                       grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-status', 'pa-article', 'v2', 'summary', NULL, 9, 'done', 'g', 'r', now(), 'job-bad-4', now(), now());
        RAISE EXCEPTION 'unknown status was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                       grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-no-job', 'pa-article', 'v2', 'summary', NULL, 9, 'pending', 'g', 'r', now(), NULL, now(), now());
        RAISE EXCEPTION 'a pending request without an AI job id was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('bad-job-format', 'summary', NULL, 9, 'not a job id', 'v2');
        RAISE EXCEPTION 'a malformed AI job id was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                       grant_revision, created_at, updated_at, ai_job_id)
        VALUES ('bad-grant-partial', 'pa-article', 'v2', 'summary', NULL, 9, 'pending', 'g', 'r', now(), now(), 'job-bad-5');
        RAISE EXCEPTION 'a partial grant snapshot was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, ai_job_id,
                                       created_at, updated_at)
        VALUES ('bad-no-grant', 'pa-article', 'v2', 'summary', NULL, 9, 'pending', 'job-bad-6', now(), now());
        RAISE EXCEPTION 'a pending request without any grant snapshot was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, reason,
                                       grant_reference, grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-pending-reason', 'pa-article', 'v2', 'summary', NULL, 9, 'pending', 'why', 'g', 'r', now(), 'job-bad-7',
                now(), now());
        RAISE EXCEPTION 'a pending request with a reason was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, reason,
                                       grant_reference, grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-failed-noreason', 'pa-article', 'v2', 'summary', NULL, 9, 'failed', NULL, 'g', 'r', now(), 'job-bad-8',
                now(), now());
        RAISE EXCEPTION 'a failed request without a reason was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, reason,
                                       grant_reference, grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-reason-format', 'pa-article', 'v2', 'summary', NULL, 9, 'withheld', 'free text with spaces', 'g', 'r',
                now(), 'job-bad-9', now(), now());
        RAISE EXCEPTION 'a reason that is not a machine code was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                       grant_revision, grant_checked_at, ai_job_id, owner_token, created_at, updated_at)
        VALUES ('bad-lease', 'pa-article', 'v2', 'summary', NULL, 9, 'pending', 'g', 'r', now(), 'job-bad-10', 'token', now(),
                now());
        RAISE EXCEPTION 'an owner token without a lease was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, result_version,
                                       grant_reference, grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('bad-pending-result', 'pa-article', 'v2', 'summary', NULL, 9, 'pending', 'result-x', 'g', 'r', now(),
                'job-bad-11', now(), now());
        RAISE EXCEPTION 'a pending request with a result version was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    -- ---------------------------------------------------------------- document_analyses: pending serialisation
    BEGIN
        PERFORM pg_temp.pending('da-s1-again', 'summary', NULL, 2, 'job-s1-again');
        RAISE EXCEPTION 'a second pending summary of one version was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('da-t1-again', 'sentiment', 'proof-co-a', 2, 'job-t1-again');
        RAISE EXCEPTION 'a second pending sentiment of one company and version was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('da-dup-job', 'summary', NULL, 7, 'job-s1', 'v2');
        RAISE EXCEPTION 'a duplicate AI job id was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;

    -- ---------------------------------------------------------------- lifecycle: pending -> one terminal state
    UPDATE document_analyses SET owner_token = 'worker-1', lease_until = now() + interval '1 minute', updated_at = now()
    WHERE id = 'da-t1';
    UPDATE document_analyses SET owner_token = NULL, lease_until = NULL WHERE id = 'da-t1';
    BEGIN
        UPDATE document_analyses SET status = 'not_requested' WHERE id = 'da-s1';
        RAISE EXCEPTION 'pending -> not_requested was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET stage = 'sentiment', company_id = 'proof-co-a' WHERE id = 'da-s1';
        RAISE EXCEPTION 'the stage of a request was changed';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET article_version = 'v2' WHERE id = 'da-s1';
        RAISE EXCEPTION 'the article version of a request was changed';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET request_no = 5 WHERE id = 'da-s1';
        RAISE EXCEPTION 'the request number was changed';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET ai_job_id = 'job-other' WHERE id = 'da-s1';
        RAISE EXCEPTION 'the issued AI job id was changed';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET grant_revision = 'rev-2' WHERE id = 'da-s1';
        RAISE EXCEPTION 'the grant snapshot was changed';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET created_at = now() + interval '1 day' WHERE id = 'da-s1';
        RAISE EXCEPTION 'the creation time was changed';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;

    -- A result needs every one of its parts and the model that produced it, and its references must exist.
    BEGIN
        UPDATE document_analyses SET status = 'available', result = '{}'::jsonb, result_version = 'result-1',
            result_artifact_id = 'pa-result-1', exact_receipt_id = 'pa-exact-1', produced_at = now(), model = 'm',
            prompt_version = 'p' WHERE id = 'da-s1';
        RAISE EXCEPTION 'an available result without its semantic receipt was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET status = 'available', result = '[]'::jsonb, result_version = 'result-1',
            result_artifact_id = 'pa-result-1', exact_receipt_id = 'pa-exact-1', semantic_receipt_id = 'pa-sem-1',
            produced_at = now(), model = 'm', prompt_version = 'p' WHERE id = 'da-s1';
        RAISE EXCEPTION 'a result that is not a JSON object was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET status = 'available', result = '{}'::jsonb, result_version = 'result-1',
            result_artifact_id = 'pa-result-1', exact_receipt_id = 'pa-exact-1', semantic_receipt_id = 'pa-sem-1',
            produced_at = now() WHERE id = 'da-s1';
        RAISE EXCEPTION 'an available result without a model was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET status = 'withheld', reason = 'semantic_hold', result_version = 'result-1'
        WHERE id = 'da-s1';
        RAISE EXCEPTION 'a withheld request with a result version was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.available('da-s1', 'result-1', 'pa-result-missing', 'pa-exact-1', 'pa-sem-1');
        RAISE EXCEPTION 'a result artifact that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.available('da-s1', 'result-1', 'pa-result-1', 'pa-exact-missing', 'pa-sem-1');
        RAISE EXCEPTION 'an exact receipt that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;

    PERFORM pg_temp.available('da-s1', 'result-1', 'pa-result-1', 'pa-exact-1', 'pa-sem-1');
    UPDATE document_analyses SET status = 'failed', reason = 'provider_http_500', model = 'authored-synthetic' WHERE id = 'da-t1';
    UPDATE document_analyses SET status = 'withheld', reason = 'semantic_hold' WHERE id = 'da-t2';

    -- A finished request is history: only the observation of a later revocation and its own time may change.
    BEGIN
        UPDATE document_analyses SET status = 'withheld', reason = 'late' WHERE id = 'da-s1';
        RAISE EXCEPTION 'an available result was withheld afterwards';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET result = '{"schemaVersion":"changed"}'::jsonb WHERE id = 'da-s1';
        RAISE EXCEPTION 'a finished result was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET result_version = 'result-2' WHERE id = 'da-s1';
        RAISE EXCEPTION 'a finished result version was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET status = 'available' WHERE id = 'da-t1';
        RAISE EXCEPTION 'a failed request became available';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET reason = 'other_reason' WHERE id = 'da-t2';
        RAISE EXCEPTION 'a withheld reason was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE document_analyses SET model = 'rewritten' WHERE id = 'da-t1';
        RAISE EXCEPTION 'a finished request model was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    UPDATE document_analyses SET revoked_at = now(), updated_at = now() WHERE id = 'da-s1';
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 1 THEN
        RAISE EXCEPTION 'the revocation observation of a finished request could not be recorded';
    END IF;

    -- ---------------------------------------------------------------- explicit re-request after a finished request
    BEGIN
        PERFORM pg_temp.pending('da-s1-dup-no', 'summary', NULL, 1, 'job-dup-no');
        RAISE EXCEPTION 'a request number was used twice in one summary scope';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('da-t1-dup-no', 'sentiment', 'proof-co-a', 1, 'job-dup-no-t');
        RAISE EXCEPTION 'a request number was used twice in one sentiment scope';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    PERFORM pg_temp.pending('da-s2', 'summary', NULL, 2, 'job-s2');
    PERFORM pg_temp.pending('da-t1-2', 'sentiment', 'proof-co-a', 2, 'job-t1-2');
    -- The same result version can be recorded once: a second available request with the same worker result would be a bug.
    BEGIN
        PERFORM pg_temp.available('da-s2', 'result-1', 'pa-result-2', 'pa-exact-2', 'pa-sem-2');
        RAISE EXCEPTION 'a result version was accepted twice';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    PERFORM pg_temp.available('da-s2', 'result-2', 'pa-result-2', 'pa-exact-2', 'pa-sem-2');

    -- ---------------------------------------------------------------- references
    BEGIN
        INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference,
                                       grant_revision, grant_checked_at, ai_job_id, created_at, updated_at)
        VALUES ('fk-version', 'pa-article', 'v-missing', 'summary', NULL, 1, 'pending', 'g', 'r', now(), 'job-fk-1', now(), now());
        RAISE EXCEPTION 'a request for a version that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        PERFORM pg_temp.pending('fk-company', 'sentiment', 'proof-co-missing', 1, 'job-fk-2');
        RAISE EXCEPTION 'a sentiment of a company that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM companies WHERE id = 'proof-co-a';
        RAISE EXCEPTION 'a company with analyses was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM artifacts WHERE id = 'pa-result-1';
        RAISE EXCEPTION 'a referenced result artifact was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM article_versions WHERE article_id = 'pa-article' AND version = 'v1';
        RAISE EXCEPTION 'an analysed article version was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;

    -- ---------------------------------------------------------------- evidence
    INSERT INTO evidence (id, article_id, article_version, text_artifact_id, summary_analysis_id, quote, start_offset, end_offset,
                          offset_unit, input_kind, raw_locator_ids, quote_verified, verification_artifact_id, verified_at, created_at)
    VALUES ('ev-1', 'pa-article', 'v1', 'pa-text', NULL, E'\U0001F600한', 0, 2, 'unicode_code_point', 'body', '["raw-1"]'::jsonb,
            TRUE, 'pa-exact-1', now(), now());
    -- offsets count code points: the same quote taken as UTF-16 units (3) is not its length
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-utf16', 'pa-article', 'v1', 'pa-text', E'\U0001F600한', 0, 3, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'UTF-16 offsets were accepted as code point offsets';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-empty', 'pa-article', 'v1', 'pa-text', '', 4, 4, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'an empty quote was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-negative', 'pa-article', 'v1', 'pa-text', 'ab', -1, 1, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'a negative start was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-unit', 'pa-article', 'v1', 'pa-text', 'ab', 0, 2, 'utf16', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'an unknown offset unit was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-kind', 'pa-article', 'v1', 'pa-text', 'ab', 0, 2, 'unicode_code_point', 'raw', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'an unknown input kind was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-summary-kind', 'pa-article', 'v1', 'pa-text', 'ab', 0, 2, 'unicode_code_point', 'summary', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'a summary-kind evidence without its summary analysis was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, summary_analysis_id, quote, start_offset,
                              end_offset, offset_unit, input_kind, raw_locator_ids, created_at)
        VALUES ('ev-body-link', 'pa-article', 'v1', 'pa-text', 'da-s1', 'ab', 0, 2, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'a body evidence linked to a summary analysis was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    INSERT INTO evidence (id, article_id, article_version, text_artifact_id, summary_analysis_id, quote, start_offset, end_offset,
                          offset_unit, input_kind, raw_locator_ids, created_at)
    VALUES ('ev-summary', 'pa-article', 'v1', 'pa-text', 'da-s1', 'ab', 0, 2, 'unicode_code_point', 'summary', '["raw-1"]'::jsonb, now());
    FOR i IN 1..4 LOOP
        BEGIN
            INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                                  input_kind, raw_locator_ids, created_at)
            VALUES ('ev-locators-' || i, 'pa-article', 'v1', 'pa-text', 'ab', 0, 2, 'unicode_code_point', 'body',
                    (ARRAY['[]', '"raw-1"', '[1]', '{"a":"b"}'])[i]::jsonb, now());
            RAISE EXCEPTION 'raw locator ids variant % was accepted', i;
        EXCEPTION WHEN check_violation THEN NULL;
        END;
    END LOOP;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, quote_verified, created_at)
        VALUES ('ev-unverified', 'pa-article', 'v1', 'pa-text', 'ab', 0, 2, 'unicode_code_point', 'body', '["raw-1"]'::jsonb,
                TRUE, now());
        RAISE EXCEPTION 'a verified quote without its verification artifact was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-1', 'pa-article', 'v1', 'pa-text', 'ab', 0, 2, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'a duplicate evidence id was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-fk-version', 'pa-article', 'v-missing', 'pa-text', 'ab', 0, 2, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'evidence of a version that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO evidence (id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset, offset_unit,
                              input_kind, raw_locator_ids, created_at)
        VALUES ('ev-fk-text', 'pa-article', 'v1', 'pa-text-missing', 'ab', 0, 2, 'unicode_code_point', 'body', '["raw-1"]'::jsonb, now());
        RAISE EXCEPTION 'evidence of a text artifact that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE evidence SET quote = 'changed' WHERE id = 'ev-1';
        RAISE EXCEPTION 'evidence was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE evidence SET verified_at = now() WHERE id = 'ev-1';
        RAISE EXCEPTION 'evidence verification time was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM document_analyses WHERE id = 'da-s1';
        RAISE EXCEPTION 'an analysis with summary-input evidence was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;

    -- ---------------------------------------------------------------- ai_executions
    INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, ai_job_id, ai_attempt_id, stage,
                               receipt_artifact_id, grant_id, grant_revision, grant_scope, provider, model, prompt_version,
                               input_tokens, output_tokens, started_at, finished_at)
    VALUES ('aix-1', 'news-analysis', 'replay', 'succeeded', 'da-s1', 'job-s1', 'attempt-1', 'document-summary', 'pa-rcpt-1',
            'grant-1', 'rev-1', '{"sourceId":"s","requiredOperations":["read"],"requiredPurposes":["document-summary"],"requiredRecipients":["authored-replay"]}'::jsonb,
            'authored-replay', 'authored-synthetic', 'prompt-1', NULL, NULL, now(), now());
    FOR i IN 1..3 LOOP
        BEGIN
            INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, started_at)
            VALUES ('bad-enum-' || i, (ARRAY['chat', 'news-analysis', 'news-analysis'])[i],
                    (ARRAY['replay', 'batch', 'replay'])[i], (ARRAY['succeeded', 'succeeded', 'queued'])[i], 'da-s1', now());
            RAISE EXCEPTION 'enum variant % was accepted', i;
        EXCEPTION WHEN check_violation THEN NULL;
        END;
    END LOOP;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, started_at)
        VALUES ('bad-no-owner', 'news-analysis', 'replay', 'succeeded', now());
        RAISE EXCEPTION 'an execution without an owner or context was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, chat_job_id, briefing_attempt_id, started_at)
        VALUES ('bad-two-owners', 'chatbot', 'live', 'succeeded', 'chat-1', 'attempt-x', now());
        RAISE EXCEPTION 'an execution with two execution owners was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, ai_job_id, started_at)
        VALUES ('bad-half-attempt', 'news-analysis', 'replay', 'succeeded', 'da-s1', 'job-s1', now());
        RAISE EXCEPTION 'an AI job without its attempt was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, input_tokens, started_at)
        VALUES ('bad-tokens', 'news-analysis', 'replay', 'succeeded', 'da-s1', -1, now());
        RAISE EXCEPTION 'negative tokens were accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, estimated_cost, started_at)
        VALUES ('bad-cost', 'news-analysis', 'replay', 'succeeded', 'da-s1', -0.01, now());
        RAISE EXCEPTION 'a negative cost was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, attempt_no, started_at)
        VALUES ('bad-attempt-no', 'news-analysis', 'replay', 'succeeded', 'da-s1', 0, now());
        RAISE EXCEPTION 'attempt number 0 was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    FOR i IN 1..4 LOOP
        BEGIN
            INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, grant_scope, started_at)
            VALUES ('bad-scope-' || i, 'news-analysis', 'replay', 'succeeded', 'da-s1', (ARRAY[
                '[]',
                '{"sourceId":"s","requiredOperations":[],"requiredPurposes":[]}',
                '{"sourceId":1,"requiredOperations":[],"requiredPurposes":[],"requiredRecipients":[]}',
                '{"sourceId":"s","requiredOperations":"read","requiredPurposes":[],"requiredRecipients":[]}'])[i]::jsonb, now());
            RAISE EXCEPTION 'grant scope variant % was accepted', i;
        EXCEPTION WHEN check_violation THEN NULL;
        END;
    END LOOP;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, ai_job_id, ai_attempt_id, started_at)
        VALUES ('aix-dup', 'news-analysis', 'replay', 'succeeded', 'da-s1', 'job-s1', 'attempt-1', now());
        RAISE EXCEPTION 'the same AI attempt was counted twice';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    -- Executions without an AI attempt (an app-side replay or save-only record) are not de-duplicated by the attempt index.
    INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, started_at) VALUES
        ('aix-local-1', 'news-analysis', 'save_only', 'succeeded', 'da-s1', now()),
        ('aix-local-2', 'news-analysis', 'save_only', 'succeeded', 'da-s1', now());
    -- A document analysis that is the only owner must be the analysis of the AI job the receipt belongs to ...
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, ai_job_id, ai_attempt_id, started_at)
        VALUES ('aix-wrong-owner', 'news-analysis', 'replay', 'succeeded', 'da-s2', 'job-s1', 'attempt-9', now());
        RAISE EXCEPTION 'an attempt of another analysis job was attached to a document analysis';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    -- ... but it may be extra context of another owner's execution.
    INSERT INTO ai_executions (id, feature, execution_mode, status, chat_job_id, document_analysis_id, ai_job_id, ai_attempt_id,
                               started_at)
    VALUES ('aix-context', 'chatbot', 'replay', 'succeeded', 'chat-1', 'da-s2', 'job-chat', 'attempt-chat', now());
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, receipt_artifact_id, started_at)
        VALUES ('aix-fk-receipt', 'news-analysis', 'replay', 'succeeded', 'da-s1', 'pa-rcpt-missing', now());
        RAISE EXCEPTION 'a receipt artifact that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO ai_executions (id, feature, execution_mode, status, document_analysis_id, started_at)
        VALUES ('aix-fk-analysis', 'news-analysis', 'replay', 'succeeded', 'da-missing', now());
        RAISE EXCEPTION 'a document analysis that does not exist was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    -- A receipt-backed execution is occurrence history; one without a receipt may still move on.
    BEGIN
        UPDATE ai_executions SET status = 'failed' WHERE id = 'aix-1';
        RAISE EXCEPTION 'a receipt-backed execution was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE ai_executions SET input_tokens = 5 WHERE id = 'aix-1';
        RAISE EXCEPTION 'receipt-backed usage was rewritten';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    UPDATE ai_executions SET status = 'failed', error_code = 'late_failure', finished_at = now() WHERE id = 'aix-local-1';
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 1 THEN
        RAISE EXCEPTION 'an execution without a receipt could not be completed';
    END IF;
    BEGIN
        DELETE FROM artifacts WHERE id = 'pa-rcpt-1';
        RAISE EXCEPTION 'a referenced receipt artifact was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END $$;

ROLLBACK;
