-- Immutable, complete round candidate inputs. No member data or changes to published originals.
CREATE TABLE briefing_personal_pools (
    id text PRIMARY KEY,
    round_id text NOT NULL REFERENCES briefing_rounds(id),
    input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[a-f0-9]{64}$'),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot)='object'),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 = encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(round_id, input_sha256)
);
CREATE INDEX briefing_personal_pool_round ON briefing_personal_pools(round_id, created_at DESC, id);
CREATE FUNCTION preserve_briefing_personal_pool() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'briefing personal candidate pools are immutable'; END $$;
CREATE TRIGGER briefing_personal_pool_immutable BEFORE UPDATE OR DELETE ON briefing_personal_pools
FOR EACH ROW EXECUTE FUNCTION preserve_briefing_personal_pool();
