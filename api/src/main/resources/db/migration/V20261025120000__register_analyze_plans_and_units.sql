-- Separate analysis processing from collection. Existing jobs and internal projection retain their meanings.
CREATE TABLE analysis_plans (
    plan_id text PRIMARY KEY CHECK (plan_id ~ '^s2plan-[0-9a-f]{64}$'),
    plan_digest text NOT NULL CHECK (plan_digest ~ '^[0-9a-f]{64}$'),
    service_binding text NOT NULL CHECK (service_binding ~ '^[0-9a-f]{64}$'),
    expected_principal text NOT NULL CHECK (expected_principal ~ '^[a-z][a-z0-9-]{0,62}$'),
    registered_at timestamptz NOT NULL,
    registered_by text NOT NULL,
    admission_intent_at timestamptz,
    admission_id text UNIQUE CHECK (admission_id ~ '^pa-[0-9a-f]{64}$'),
    accepted_at timestamptz,
    policy_revision bigint CHECK (policy_revision > 0),
    policy_digest text CHECK (policy_digest ~ '^[0-9a-f]{64}$'),
    receipt_sha256 text CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    manifest_digest text CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
    manifest jsonb,
    last_authority_state text CHECK (last_authority_state IN ('active', 'inactive')),
    last_authority_reason text,
    authority_observed_at timestamptz,
    last_admission_code text,
    CONSTRAINT ck_analysis_plan_admission_tuple CHECK (
        num_nonnulls(admission_id, accepted_at, policy_revision, policy_digest, receipt_sha256, manifest_digest, manifest) IN (0, 7)),
    CONSTRAINT ck_analysis_plan_authority CHECK ((
        (last_authority_state IS NULL AND last_authority_reason IS NULL AND authority_observed_at IS NULL)
        OR (last_authority_state = 'active' AND last_authority_reason IS NULL AND authority_observed_at IS NOT NULL)
        OR (last_authority_state = 'inactive' AND last_authority_reason ~ '^[a-z][a-z0-9_]{0,79}$' AND authority_observed_at IS NOT NULL)) IS TRUE),
    CONSTRAINT ck_analysis_plan_manifest CHECK (manifest IS NULL OR ((
        jsonb_typeof(manifest) = 'object' AND manifest->>'schemaVersion' = 'zoop-ai-plan-manifest-1'
        AND manifest - ARRAY['schemaVersion','planId','planDigest','receiptSha256','principal','round','provenance','units','manifestDigest'] = '{}'::jsonb
        AND manifest ?& ARRAY['schemaVersion','planId','planDigest','receiptSha256','principal','round','provenance','units','manifestDigest']
        AND manifest->>'planId' = plan_id AND manifest->>'planDigest' = plan_digest
        AND manifest->>'principal' = expected_principal AND manifest->>'receiptSha256' = receipt_sha256
        AND manifest->>'manifestDigest' = manifest_digest AND jsonb_typeof(manifest->'units') = 'array'
        AND jsonb_array_length(manifest->'units') > 0) IS TRUE))
);

CREATE TABLE analysis_plan_units (
    plan_id text NOT NULL REFERENCES analysis_plans(plan_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 1),
    unit_key text NOT NULL,
    s2_job_id text NOT NULL UNIQUE,
    s2_approved_request_digest text NOT NULL CHECK (s2_approved_request_digest ~ '^[0-9a-f]{64}$'),
    s2_input_digest text NOT NULL CHECK (s2_input_digest ~ '^[0-9a-f]{64}$'),
    s3_job_id text NOT NULL UNIQUE,
    s2_submit jsonb NOT NULL,
    s3_submit jsonb NOT NULL,
    s3_input_digest text CHECK (s3_input_digest ~ '^[0-9a-f]{64}$'),
    s2_checkpoint jsonb NOT NULL,
    s3_checkpoint jsonb NOT NULL,
    PRIMARY KEY(plan_id, ordinal),
    UNIQUE(plan_id, unit_key),
    CHECK (unit_key = s2_job_id),
    CHECK (jsonb_typeof(s2_submit) = 'object' AND jsonb_typeof(s3_submit) = 'object'),
    CHECK (s2_checkpoint->>'schemaVersion' = 'zoop-app-analyze-plan-stage-1'
        AND s3_checkpoint->>'schemaVersion' = 'zoop-app-analyze-plan-stage-1')
);

CREATE FUNCTION analysis_plan_stage_valid(value jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT (jsonb_typeof(value) = 'object'
        AND value ?& ARRAY['schemaVersion','state','intentAt','acceptedObservedAt','lastStatus','resultObservedAt','resultContentSha256','receipts','failureCategory','failureCode','consecutiveFailures','recoveryDispatches']
        AND value - ARRAY['schemaVersion','state','intentAt','acceptedObservedAt','lastStatus','resultObservedAt','resultContentSha256','receipts','failureCategory','failureCode','consecutiveFailures','recoveryDispatches'] = '{}'::jsonb
        AND value->>'schemaVersion' = 'zoop-app-analyze-plan-stage-1'
        AND value->>'state' IN ('unsubmitted','submit_pending','accepted','result_observed','cancel_pending','cancelled','blocked')
        AND jsonb_typeof(value->'consecutiveFailures') = 'number' AND (value->>'consecutiveFailures')::integer >= 0
        AND jsonb_typeof(value->'recoveryDispatches') = 'number' AND (value->>'recoveryDispatches')::integer >= 0
        AND (value->>'state' <> 'result_observed' OR (
            value->>'resultObservedAt' IS NOT NULL AND value->>'acceptedObservedAt' IS NOT NULL
            AND value->>'resultContentSha256' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(value->'receipts') = 'array'
            AND (value->'lastStatus'->'extraction'->>'state' = 'READY'
                 AND value->'lastStatus'->'extraction'->'delivery'->>'state' = 'AVAILABLE'
                 OR value->'lastStatus'->'relation'->>'state' = 'READY'
                 AND value->'lastStatus'->'relation'->'delivery'->>'state' = 'AVAILABLE')))) IS TRUE
$$;
ALTER TABLE analysis_plan_units ADD CONSTRAINT ck_analysis_plan_stage_schema
    CHECK (analysis_plan_stage_valid(s2_checkpoint) AND analysis_plan_stage_valid(s3_checkpoint));
ALTER TABLE analysis_plan_units ADD CONSTRAINT ck_analysis_plan_unit_ids CHECK (
    s2_job_id ~ '^[A-Za-z0-9_.-]{1,120}$' AND s2_job_id NOT IN ('.','..')
    AND s3_job_id ~ '^[A-Za-z0-9_.-]{1,120}$' AND s3_job_id NOT IN ('.','..'));

CREATE FUNCTION analysis_plans_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'analysis plan cannot be deleted' USING ERRCODE = 'restrict_violation'; END IF;
    IF (NEW.plan_id, NEW.plan_digest, NEW.service_binding, NEW.expected_principal, NEW.registered_at, NEW.registered_by)
       IS DISTINCT FROM (OLD.plan_id, OLD.plan_digest, OLD.service_binding, OLD.expected_principal, OLD.registered_at, OLD.registered_by)
       OR (OLD.admission_intent_at IS NOT NULL AND NEW.admission_intent_at IS DISTINCT FROM OLD.admission_intent_at)
       OR (OLD.admission_id IS NOT NULL AND
           (NEW.admission_id, NEW.accepted_at, NEW.policy_revision, NEW.policy_digest, NEW.receipt_sha256, NEW.manifest_digest, NEW.manifest)
           IS DISTINCT FROM (OLD.admission_id, OLD.accepted_at, OLD.policy_revision, OLD.policy_digest, OLD.receipt_sha256, OLD.manifest_digest, OLD.manifest)) THEN
        RAISE EXCEPTION 'analysis plan binding is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER tr_analysis_plans_guard BEFORE UPDATE OR DELETE ON analysis_plans FOR EACH ROW EXECUTE FUNCTION analysis_plans_guard();

CREATE FUNCTION analysis_plan_units_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE stage text;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'analysis unit cannot be deleted' USING ERRCODE = 'restrict_violation'; END IF;
    IF (NEW.plan_id, NEW.ordinal, NEW.unit_key, NEW.s2_job_id, NEW.s2_approved_request_digest, NEW.s2_input_digest, NEW.s3_job_id, NEW.s2_submit, NEW.s3_submit)
       IS DISTINCT FROM (OLD.plan_id, OLD.ordinal, OLD.unit_key, OLD.s2_job_id, OLD.s2_approved_request_digest, OLD.s2_input_digest, OLD.s3_job_id, OLD.s2_submit, OLD.s3_submit)
       OR (OLD.s3_input_digest IS NOT NULL AND NEW.s3_input_digest IS DISTINCT FROM OLD.s3_input_digest) THEN
        RAISE EXCEPTION 'analysis unit binding is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    FOREACH stage IN ARRAY ARRAY['s2_checkpoint', 's3_checkpoint'] LOOP
        IF ((to_jsonb(OLD)->stage)->>'state' = 'result_observed' AND (to_jsonb(NEW)->stage) IS DISTINCT FROM (to_jsonb(OLD)->stage))
           OR ((to_jsonb(OLD)->stage)->>'acceptedObservedAt' IS NOT NULL AND
               (to_jsonb(NEW)->stage)->>'acceptedObservedAt' IS DISTINCT FROM (to_jsonb(OLD)->stage)->>'acceptedObservedAt') THEN
            RAISE EXCEPTION 'analysis observation is immutable' USING ERRCODE = 'restrict_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;
CREATE TRIGGER tr_analysis_plan_units_guard BEFORE UPDATE OR DELETE ON analysis_plan_units FOR EACH ROW EXECUTE FUNCTION analysis_plan_units_guard();

-- Deferred validation covers both directions: admission cannot commit a prefix; units cannot be appended/rebound later.
CREATE FUNCTION analysis_plan_complete_units() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p analysis_plans; key text; unit jsonb;
BEGIN
    IF TG_TABLE_NAME = 'analysis_plans' AND TG_OP = 'UPDATE' THEN
        IF OLD.admission_id IS NOT DISTINCT FROM NEW.admission_id THEN RETURN NULL; END IF;
    END IF;
    key := NEW.plan_id;
    SELECT * INTO p FROM analysis_plans WHERE plan_id = key;
    IF p.admission_id IS NULL THEN
        IF EXISTS (SELECT 1 FROM analysis_plan_units WHERE plan_id = key) THEN RAISE EXCEPTION 'units before admission'; END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'analysis_plan_units' THEN
        unit := p.manifest->'units'->(NEW.ordinal - 1);
        IF unit IS NULL OR NEW.unit_key IS DISTINCT FROM unit->>'unitKey'
           OR NEW.s2_job_id IS DISTINCT FROM unit->'extractionSubmit'->>'jobId'
           OR NEW.s2_approved_request_digest IS DISTINCT FROM unit->'extractionSubmit'->>'approvedRequestDigest'
           OR NEW.s2_input_digest IS DISTINCT FROM unit->>'extractionInputDigest'
           OR NEW.s3_job_id IS DISTINCT FROM unit->'relationSubmit'->>'jobId'
           OR NEW.s2_submit IS DISTINCT FROM unit->'extractionSubmit'
           OR NEW.s3_submit IS DISTINCT FROM unit->'relationSubmit' THEN
            RAISE EXCEPTION 'analysis unit differs from sealed manifest' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NULL;
    END IF;
    IF (SELECT count(*) FROM analysis_plan_units WHERE plan_id = key) <> jsonb_array_length(p.manifest->'units')
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements(p.manifest->'units') WITH ORDINALITY AS m(unit, n)
           LEFT JOIN analysis_plan_units u ON u.plan_id = key AND u.ordinal = m.n
           WHERE u.ordinal IS NULL OR u.unit_key IS DISTINCT FROM m.unit->>'unitKey'
             OR u.s2_job_id IS DISTINCT FROM m.unit->'extractionSubmit'->>'jobId'
             OR u.s2_approved_request_digest IS DISTINCT FROM m.unit->'extractionSubmit'->>'approvedRequestDigest'
             OR u.s2_input_digest IS DISTINCT FROM m.unit->>'extractionInputDigest'
             OR u.s3_job_id IS DISTINCT FROM m.unit->'relationSubmit'->>'jobId'
             OR u.s2_submit IS DISTINCT FROM m.unit->'extractionSubmit'
             OR u.s3_submit IS DISTINCT FROM m.unit->'relationSubmit') THEN
        RAISE EXCEPTION 'analysis admission requires exact complete unit set' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER tr_analysis_plan_complete AFTER INSERT OR UPDATE ON analysis_plans DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis_plan_complete_units();
CREATE CONSTRAINT TRIGGER tr_analysis_units_complete AFTER INSERT ON analysis_plan_units DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis_plan_complete_units();

ALTER TABLE analysis_jobs DROP CONSTRAINT ck_analysis_jobs_kind;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_kind CHECK (kind IN ('ingest','revalidate','project','analyze_plan'));
ALTER TABLE analysis_jobs ADD COLUMN plan_id text REFERENCES analysis_plans(plan_id) ON UPDATE RESTRICT ON DELETE RESTRICT;
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_plan_kind CHECK ((kind = 'analyze_plan') = (plan_id IS NOT NULL) AND (plan_id IS NULL OR scope = 'admin'));
CREATE INDEX ix_analysis_jobs_plan_history ON analysis_jobs(plan_id, requested_at, id) WHERE plan_id IS NOT NULL;

CREATE OR REPLACE FUNCTION analysis_jobs_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.kind, NEW.scope, NEW.label, NEW.reason, NEW.requested_by, NEW.requested_at, NEW.retry_of, NEW.command_key, NEW.input, NEW.plan_id)
       IS DISTINCT FROM (OLD.id, OLD.kind, OLD.scope, OLD.label, OLD.reason, OLD.requested_by, OLD.requested_at, OLD.retry_of, OLD.command_key, OLD.input, OLD.plan_id) THEN
        RAISE EXCEPTION 'analysis job command is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.kind = 'analyze_plan' AND OLD.status IN ('succeeded','failed','cancelled') AND
       (NEW.status, NEW.started_at, NEW.finished_at, NEW.checkpoint, NEW.error, NEW.attempts, NEW.cancel_requested)
       IS DISTINCT FROM (OLD.status, OLD.started_at, OLD.finished_at, OLD.checkpoint, OLD.error, OLD.attempts, OLD.cancel_requested) THEN
        RAISE EXCEPTION 'analysis outcome is frozen' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.kind = 'analyze_plan' AND (
        jsonb_array_length(NEW.attempts) < jsonb_array_length(OLD.attempts)
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(OLD.attempts) WITH ORDINALITY AS a(attempt,n)
                   WHERE a.attempt->>'status' IN ('succeeded','failed','cancelled')
                     AND NEW.attempts->(a.n::integer-1) IS DISTINCT FROM a.attempt)) THEN
        RAISE EXCEPTION 'settled analysis attempts are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION analysis_jobs_plan_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind = 'analyze_plan' AND NOT EXISTS (
        SELECT 1 FROM analysis_plans p WHERE p.plan_id = NEW.plan_id AND NEW.input = jsonb_build_object(
            'schemaVersion','zoop-app-analyze-plan-1','planId',p.plan_id,'planDigest',p.plan_digest)) THEN
        RAISE EXCEPTION 'analysis job requires exact registered plan input' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER tr_analysis_jobs_plan_insert BEFORE INSERT ON analysis_jobs FOR EACH ROW EXECUTE FUNCTION analysis_jobs_plan_insert();

ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_plan_results CHECK (
    kind <> 'analyze_plan' OR (ingest IS NULL AND report IS NULL AND flush IS NULL
    AND ledger_before IS NULL AND ledger_after IS NULL AND target_version_id IS NULL));
ALTER TABLE analysis_jobs ADD CONSTRAINT ck_analysis_jobs_plan_checkpoint CHECK (kind <> 'analyze_plan' OR ((
    jsonb_typeof(checkpoint)='object'
    AND checkpoint ?& ARRAY['schemaVersion','phase','activeOrdinal','terminalSummary','lastFailureCategory']
    AND checkpoint - ARRAY['schemaVersion','phase','activeOrdinal','terminalSummary','lastFailureCategory']='{}'::jsonb
    AND checkpoint->>'schemaVersion'='zoop-app-analyze-plan-checkpoint-1'
    AND checkpoint->>'phase' IN ('awaiting_admission','admitting','extracting','relating','cancelling','ready','failed','cancelled')
    AND (status NOT IN ('succeeded','failed','cancelled') OR jsonb_typeof(checkpoint->'terminalSummary')='object')) IS TRUE));
