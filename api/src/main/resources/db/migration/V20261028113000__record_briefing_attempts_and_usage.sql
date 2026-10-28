-- FS068 producer ledger. Existing publications/receipts are never backfilled as new live calls.
CREATE TABLE briefing_attempts (
    id text PRIMARY KEY,
    round_id text NOT NULL REFERENCES briefing_rounds(id) ON DELETE RESTRICT,
    attempt_no integer NOT NULL CHECK (attempt_no >= 1),
    request_key text NOT NULL UNIQUE CHECK (btrim(request_key) <> ''),
    purpose text NOT NULL CHECK (purpose IN ('generation', 'outlook')),
    trigger text NOT NULL CHECK (trigger IN ('scheduler', 'admin')),
    admin_id text REFERENCES admins(id) ON DELETE RESTRICT,
    admin_email_snapshot text,
    owner_token text NOT NULL UNIQUE CHECK (btrim(owner_token) <> ''),
    status text NOT NULL CHECK (status IN ('queued','running','verifying','completed','failed','cancelled')),
    stages jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(stages) = 'object'),
    input_artifact_id text REFERENCES artifacts(id) ON DELETE RESTRICT,
    failure_reason text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    lease_until timestamptz NOT NULL,
    CHECK (trigger <> 'admin' OR admin_id IS NOT NULL),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK ((status IN ('queued','running','verifying')) = (finished_at IS NULL)),
    UNIQUE(round_id,attempt_no)
);
CREATE UNIQUE INDEX ux_briefing_attempt_active ON briefing_attempts(round_id)
    WHERE status IN ('queued','running','verifying');
CREATE INDEX ix_briefing_attempt_started ON briefing_attempts(started_at,round_id);
ALTER TABLE ai_executions ADD CONSTRAINT fk_ai_executions_briefing_attempt
    FOREIGN KEY (briefing_attempt_id) REFERENCES briefing_attempts(id) ON DELETE RESTRICT;
-- NULL means transmission is not established; false is reserved for a proved unsent operation.
ALTER TABLE ai_executions ADD COLUMN transmission_confirmed boolean;
ALTER TABLE ai_executions ADD COLUMN retry_unit_id text;
ALTER TABLE ai_executions ADD COLUMN cost_basis jsonb;
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_execution_briefing_feature CHECK (
    briefing_attempt_id IS NULL OR feature IN ('briefing','briefing-outlook'));
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_execution_briefing_local CHECK (
    briefing_attempt_id IS NULL OR execution_mode='live' OR
    (ai_job_id IS NULL AND ai_attempt_id IS NULL AND input_tokens IS NULL AND output_tokens IS NULL
        AND actual_cost IS NULL AND estimated_cost IS NULL AND transmission_confirmed=false AND retry_unit_id IS NULL));
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_execution_briefing_cost CHECK (
    briefing_attempt_id IS NULL OR estimated_cost IS NULL OR (currency IS NOT NULL AND cost_basis IS NOT NULL));
CREATE INDEX ix_ai_execution_briefing ON ai_executions(briefing_attempt_id,started_at);

CREATE FUNCTION protect_briefing_attempt_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'briefing attempt history cannot be deleted'; END IF;
    IF OLD.status IN ('completed','failed','cancelled') THEN
        RAISE EXCEPTION 'finished briefing attempt is immutable';
    END IF;
    IF NEW.stages->'purpose' IS DISTINCT FROM OLD.stages->'purpose'
        OR NEW.stages->'inputSha256' IS DISTINCT FROM OLD.stages->'inputSha256' THEN
        RAISE EXCEPTION 'briefing attempt input identity is immutable';
    END IF;
    IF ROW(NEW.id,NEW.round_id,NEW.attempt_no,NEW.request_key,NEW.purpose,NEW.trigger,
           NEW.admin_id,NEW.admin_email_snapshot,NEW.owner_token,NEW.input_artifact_id,NEW.started_at)
       IS DISTINCT FROM ROW(OLD.id,OLD.round_id,OLD.attempt_no,OLD.request_key,OLD.purpose,OLD.trigger,
           OLD.admin_id,OLD.admin_email_snapshot,OLD.owner_token,OLD.input_artifact_id,OLD.started_at) THEN
        RAISE EXCEPTION 'briefing attempt identity is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER tr_briefing_attempt_history BEFORE UPDATE OR DELETE ON briefing_attempts
    FOR EACH ROW EXECUTE FUNCTION protect_briefing_attempt_history();

CREATE FUNCTION check_briefing_attempt_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r briefing_rounds; a briefing_attempts; rid text;
BEGIN
    IF TG_TABLE_NAME='briefing_rounds' THEN rid := NEW.id; ELSE rid := NEW.round_id; END IF;
    SELECT * INTO r FROM briefing_rounds WHERE id=rid;
    IF NOT FOUND THEN RETURN NEW; END IF;
    SELECT * INTO a FROM briefing_attempts WHERE round_id=rid AND status IN ('queued','running','verifying');
    IF r.status IN ('generating','verifying') THEN
        IF a.id IS NULL OR a.purpose<>'generation' OR a.owner_token<>r.generation_token OR a.lease_until<>r.lease_until THEN
            RAISE EXCEPTION 'active round must have one matching generation owner';
        END IF;
    ELSIF a.id IS NOT NULL AND a.purpose='generation' THEN
        RAISE EXCEPTION 'active generation attempt requires an active round';
    END IF;
    RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER tr_briefing_attempt_owner AFTER INSERT OR UPDATE ON briefing_attempts
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_briefing_attempt_owner();
CREATE CONSTRAINT TRIGGER tr_briefing_round_attempt_owner AFTER INSERT OR UPDATE ON briefing_rounds
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_briefing_attempt_owner();

-- A stale worker may still report its expense, but must never publish its result.
CREATE FUNCTION fence_briefing_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('generating','verifying') AND NEW.published_at IS NOT NULL AND OLD.published_at IS NULL THEN
        IF OLD.lease_until <= clock_timestamp() OR
           current_setting('zoop.briefing.owner_token',true) IS DISTINCT FROM OLD.generation_token THEN
            RAISE EXCEPTION 'briefing publication requires the current unexpired owner';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER tr_briefing_publication_fence BEFORE UPDATE ON briefing_rounds
    FOR EACH ROW EXECUTE FUNCTION fence_briefing_publication();
