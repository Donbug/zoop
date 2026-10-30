-- Explicit member requests have immutable scope; shared analyses contain only public issue inputs.
CREATE TABLE briefing_selected_generation_jobs (
 id text PRIMARY KEY,
 member_id text NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 round_id text NOT NULL REFERENCES briefing_rounds(id),
 selection_version text NOT NULL,
 choice jsonb NOT NULL,
 request_snapshot jsonb NOT NULL,
 request_sha256 text NOT NULL CHECK(request_sha256=encode(sha256(convert_to(request_snapshot::text,'UTF8')),'hex')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','ready','partial','withheld','requires_recovery','budget_exhausted','stale','failed')),
 outcome jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 UNIQUE(member_id,round_id,selection_version)
);
CREATE INDEX selected_generation_queue ON briefing_selected_generation_jobs(created_at) WHERE status='queued';
CREATE FUNCTION preserve_selected_generation_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.member_id,NEW.round_id,NEW.selection_version,NEW.choice,NEW.request_snapshot,NEW.request_sha256)
     IS DISTINCT FROM (OLD.member_id,OLD.round_id,OLD.selection_version,OLD.choice,OLD.request_snapshot,OLD.request_sha256)
 THEN RAISE EXCEPTION 'selected briefing generation scope cannot change'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER selected_generation_scope BEFORE UPDATE ON briefing_selected_generation_jobs
FOR EACH ROW EXECUTE FUNCTION preserve_selected_generation_scope();
CREATE TABLE briefing_shared_issue_analyses (
 result_version text PRIMARY KEY, round_id text NOT NULL REFERENCES briefing_rounds(id),issue_id text NOT NULL,
 input_sha256 text NOT NULL, input_snapshot jsonb NOT NULL,
 result_record jsonb NOT NULL CHECK(result_record->>'status'='PASS'),
 view jsonb NOT NULL, view_sha256 text NOT NULL CHECK(view_sha256=encode(sha256(convert_to(view::text,'UTF8')),'hex')),
 provider_proof jsonb NOT NULL CHECK(jsonb_typeof(provider_proof)='array' AND jsonb_array_length(provider_proof)=2),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(round_id,issue_id,input_sha256)
);
CREATE TRIGGER shared_issue_analysis_immutable BEFORE UPDATE OR DELETE ON briefing_shared_issue_analyses
FOR EACH ROW EXECUTE FUNCTION preserve_briefing_personal_pool();
CREATE TABLE briefing_selected_generation_calls (
 request_sha256 text PRIMARY KEY,
 job_id text REFERENCES briefing_selected_generation_jobs(id) ON DELETE SET NULL,
 stage text NOT NULL CHECK(stage IN ('analysis','analysis-verification')),
 reserved_upper_usd numeric NOT NULL CHECK(reserved_upper_usd>=0),
 http_status integer,input_tokens bigint CHECK(input_tokens>=0),output_tokens bigint CHECK(output_tokens>=0),
 charged_upper_usd numeric CHECK(charged_upper_usd>=0),
 started_at timestamptz NOT NULL DEFAULT now(),finished_at timestamptz
);
