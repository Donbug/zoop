CREATE TABLE briefing_personal_preferences (
 id text PRIMARY KEY, member_id text NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 revision integer NOT NULL CHECK(revision>0), choice jsonb NOT NULL,
 created_at timestamptz NOT NULL, effective_from timestamptz NOT NULL CHECK(effective_from>created_at),
 UNIQUE(member_id,revision), UNIQUE(id,member_id)
);
CREATE TRIGGER preserve_personal_preference BEFORE UPDATE ON briefing_personal_preferences
 FOR EACH ROW EXECUTE FUNCTION preserve_briefing_personal_pool();
CREATE INDEX personal_preference_effective ON briefing_personal_preferences(member_id,effective_from DESC,revision DESC);
CREATE TABLE briefing_personal_deliveries (
 id text PRIMARY KEY, member_id text NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 round_id text NOT NULL REFERENCES briefing_rounds(id), preference_id text NOT NULL,
 mode text NOT NULL CHECK(mode IN ('scheduled','demo')), scheduled_at timestamptz NOT NULL,
 selection_snapshot jsonb NOT NULL, selection_sha256 text NOT NULL,
 result_snapshot jsonb, result_sha256 text,
 job_id text REFERENCES briefing_selected_generation_jobs(id) ON DELETE SET NULL,
 status text NOT NULL CHECK(status IN ('generating','ready','partial','withheld','failed')),
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 FOREIGN KEY(preference_id,member_id) REFERENCES briefing_personal_preferences(id,member_id) ON DELETE CASCADE,
 UNIQUE(member_id,round_id,preference_id,mode),
 CHECK((result_snapshot IS NULL)=(result_sha256 IS NULL)),
 CHECK((result_snapshot IS NULL)=(finished_at IS NULL))
);
CREATE UNIQUE INDEX personal_scheduled_round_once ON briefing_personal_deliveries(member_id,round_id) WHERE mode='scheduled';
CREATE OR REPLACE FUNCTION preserve_personal_delivery() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF (NEW.id,NEW.member_id,NEW.round_id,NEW.preference_id,NEW.mode,NEW.scheduled_at,NEW.selection_snapshot,NEW.selection_sha256,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.member_id,OLD.round_id,OLD.preference_id,OLD.mode,OLD.scheduled_at,OLD.selection_snapshot,OLD.selection_sha256,OLD.created_at)
 OR (OLD.result_snapshot IS NOT NULL AND (NEW.result_snapshot,NEW.result_sha256,NEW.status,NEW.finished_at) IS DISTINCT FROM (OLD.result_snapshot,OLD.result_sha256,OLD.status,OLD.finished_at))
 THEN RAISE EXCEPTION 'personal briefing delivery is immutable'; END IF; RETURN NEW; END $$;
CREATE TRIGGER preserve_personal_delivery BEFORE UPDATE ON briefing_personal_deliveries FOR EACH ROW EXECUTE FUNCTION preserve_personal_delivery();
