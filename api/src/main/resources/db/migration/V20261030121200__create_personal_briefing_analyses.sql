-- Separate member-scoped AI revisions. Never updates published payloads, candidate pools or feedback.
CREATE TABLE briefing_personal_analyses (
    member_id text NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    round_id text NOT NULL REFERENCES briefing_rounds(id),
    result_version text NOT NULL,
    selection_basis jsonb NOT NULL CHECK(jsonb_typeof(selection_basis)='object'),
    input_snapshot jsonb NOT NULL CHECK(jsonb_typeof(input_snapshot)='object'),
    result jsonb NOT NULL CHECK(result->>'status'='PASS'),
    result_sha256 text NOT NULL CHECK(result_sha256=encode(sha256(convert_to(result::text,'UTF8')),'hex')),
    provider_proof jsonb NOT NULL CHECK(jsonb_typeof(provider_proof)='array' AND jsonb_array_length(provider_proof)=2),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(member_id,result_version)
);
CREATE INDEX personal_briefing_analysis_lookup ON briefing_personal_analyses(member_id,round_id,created_at DESC);
CREATE FUNCTION preserve_personal_briefing_analysis() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'personal briefing analysis revisions cannot be updated'; END $$;
-- DELETE remains possible for member erasure; the member FK cascades private data.
CREATE TRIGGER personal_briefing_analysis_immutable BEFORE UPDATE ON briefing_personal_analyses
FOR EACH ROW EXECUTE FUNCTION preserve_personal_briefing_analysis();
