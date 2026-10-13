-- Briefing-owned storage only. graph_versions FK and generation/attempt linkage
-- are added by follow-up migrations after those owners provide their tables.
-- No public publication writer is installed by this migration.
CREATE TABLE briefing_rounds (
    id text PRIMARY KEY,
    round_date date NOT NULL,
    edition text NOT NULL CHECK (edition IN ('morning', 'evening')),
    scheduled_at timestamptz NOT NULL,
    window_from timestamptz,
    window_to timestamptz NOT NULL,
    open_start boolean NOT NULL,
    status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'missing', 'generating', 'verifying', 'published', 'failed', 'suspended')),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    stages jsonb NOT NULL DEFAULT '{}'::jsonb,
    failure_reason text,
    attempt_no integer NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
    generation_token text,
    lease_until timestamptz,
    graph_version_id text,
    review_revision bigint CHECK (review_revision >= 0),
    rule_revision bigint CHECK (rule_revision >= 0),
    published_payload jsonb,
    public_snapshot jsonb,
    schema_version text,
    payload_sha256 text CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    morning_round_id text REFERENCES briefing_rounds(id) ON DELETE RESTRICT,
    comparison_snapshot jsonb,
    generated_at timestamptz,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (round_date, edition),
    CHECK (open_start = (window_from IS NULL)),
    CHECK (window_from IS NULL OR window_from < window_to),
    CHECK (morning_round_id IS NULL OR (edition = 'evening' AND morning_round_id <> id)),
    CHECK ((status IN ('generating', 'verifying') AND generation_token IS NOT NULL AND lease_until IS NOT NULL)
        OR (status NOT IN ('generating', 'verifying') AND generation_token IS NULL AND lease_until IS NULL)),
    CHECK (status NOT IN ('published', 'suspended') OR published_at IS NOT NULL),
    CHECK (published_at IS NULL OR (status IN ('published', 'suspended') AND review_revision IS NOT NULL
        AND published_payload IS NOT NULL AND public_snapshot IS NOT NULL AND generated_at IS NOT NULL
        AND schema_version IS NOT NULL AND payload_sha256 IS NOT NULL))
);
CREATE INDEX briefing_rounds_history_idx ON briefing_rounds(round_date DESC, edition, id);
CREATE INDEX briefing_rounds_schedule_idx ON briefing_rounds(status, scheduled_at);
CREATE INDEX briefing_rounds_public_cursor_idx ON briefing_rounds(scheduled_at DESC, id DESC)
    WHERE published_at IS NOT NULL;

CREATE FUNCTION protect_briefing_round() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb; i jsonb; n integer; morning briefing_rounds;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.published_at IS NOT NULL THEN RAISE EXCEPTION 'published briefing is immutable'; END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.id, NEW.round_date, NEW.edition, NEW.scheduled_at, NEW.window_from, NEW.window_to, NEW.open_start, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id, OLD.round_date, OLD.edition, OLD.scheduled_at, OLD.window_from, OLD.window_to, OLD.open_start, OLD.created_at)
        THEN RAISE EXCEPTION 'briefing input window and identity are immutable'; END IF;
        IF OLD.published_at IS NOT NULL AND
            (to_jsonb(NEW) - ARRAY['status','revision']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','revision'])
        THEN RAISE EXCEPTION 'published briefing is immutable'; END IF;
    END IF;
    IF NEW.published_at IS NOT NULL AND (TG_OP = 'INSERT' OR OLD.published_at IS NULL) THEN
        p := NEW.published_payload;
        IF jsonb_typeof(p) IS DISTINCT FROM 'object' OR jsonb_typeof(p->'items') IS DISTINCT FROM 'array'
           OR jsonb_typeof(NEW.public_snapshot) IS DISTINCT FROM 'object'
           OR NEW.graph_version_id IS NULL OR btrim(NEW.graph_version_id) = ''
           OR p->>'id' IS DISTINCT FROM NEW.id OR p->>'date' IS DISTINCT FROM NEW.round_date::text
           OR p->>'edition' IS DISTINCT FROM NEW.edition OR p->>'graphVersion' IS DISTINCT FROM NEW.graph_version_id
           OR p->>'reviewRevision' IS DISTINCT FROM NEW.review_revision::text
           OR (p->>'ruleRevision') IS DISTINCT FROM NEW.rule_revision::text
           OR (p->>'scheduledAt')::timestamptz IS DISTINCT FROM NEW.scheduled_at
           OR (p->>'generatedAt')::timestamptz IS DISTINCT FROM NEW.generated_at
           OR jsonb_typeof(p->'dataWindow') IS DISTINCT FROM 'object'
           OR (p->'dataWindow'->>'start')::timestamptz IS DISTINCT FROM NEW.window_from
           OR (p->'dataWindow'->>'end')::timestamptz IS DISTINCT FROM NEW.window_to
           OR (p->'dataWindow'->>'openStart')::boolean IS DISTINCT FROM NEW.open_start
        THEN RAISE EXCEPTION 'invalid published briefing snapshot'; END IF;
        n := jsonb_array_length(p->'items');
        IF n > 3 THEN RAISE EXCEPTION 'briefing items exceed three'; END IF;
        FOR i IN SELECT value FROM jsonb_array_elements(p->'items') LOOP
            IF jsonb_typeof(i->'eventId') IS DISTINCT FROM 'string' OR btrim(i->>'eventId') = ''
                OR jsonb_typeof(i->'rank') IS DISTINCT FROM 'number' OR i->>'rank' NOT IN ('1','2','3')
            THEN RAISE EXCEPTION 'invalid briefing item key/rank'; END IF;
        END LOOP;
        IF (SELECT count(DISTINCT value->>'eventId') FROM jsonb_array_elements(p->'items')) <> n
            OR (SELECT count(DISTINCT value->>'rank') FROM jsonb_array_elements(p->'items')) <> n
        THEN RAISE EXCEPTION 'duplicate briefing item key/rank'; END IF;
        IF NEW.edition = 'morning' AND NEW.comparison_snapshot IS NOT NULL THEN
            RAISE EXCEPTION 'morning has no comparison';
        END IF;
        IF NEW.edition = 'evening' AND NEW.comparison_snapshot IS NULL THEN
            RAISE EXCEPTION 'evening must preserve comparison or unavailable reason';
        END IF;
        IF NEW.morning_round_id IS NOT NULL THEN
            SELECT * INTO morning FROM briefing_rounds WHERE id=NEW.morning_round_id FOR SHARE;
            IF NOT FOUND OR morning.edition <> 'morning' OR morning.round_date <> NEW.round_date OR morning.published_at IS NULL
            THEN RAISE EXCEPTION 'invalid morning comparison round'; END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER briefing_round_guard BEFORE INSERT OR UPDATE OR DELETE ON briefing_rounds
    FOR EACH ROW EXECUTE FUNCTION protect_briefing_round();
