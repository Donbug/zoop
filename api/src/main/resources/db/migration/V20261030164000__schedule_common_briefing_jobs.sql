-- Common scheduled work is distinct from the immutable published round.
CREATE TABLE briefing_common_schedule_jobs (
 id text PRIMARY KEY, round_date date NOT NULL, edition text NOT NULL CHECK(edition IN ('morning','evening')),
 scheduled_at timestamptz NOT NULL, window_from timestamptz NOT NULL CHECK(window_from<scheduled_at),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','requires_recovery')),
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 UNIQUE(round_date,edition)
);
CREATE OR REPLACE FUNCTION preserve_common_briefing_slot() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF (NEW.id,NEW.round_date,NEW.edition,NEW.scheduled_at,NEW.window_from,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.round_date,OLD.edition,OLD.scheduled_at,OLD.window_from,OLD.created_at)
 OR (OLD.status='completed' AND NEW IS DISTINCT FROM OLD)
 THEN RAISE EXCEPTION 'common briefing schedule slot is immutable'; END IF; RETURN NEW; END $$;
CREATE TRIGGER preserve_common_briefing_slot BEFORE UPDATE ON briefing_common_schedule_jobs
 FOR EACH ROW EXECUTE FUNCTION preserve_common_briefing_slot();
CREATE TABLE briefing_personal_slot_eligibility (
 member_id text NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 scheduled_at timestamptz NOT NULL, observed_at timestamptz NOT NULL,
 has_companies boolean NOT NULL, PRIMARY KEY(member_id,scheduled_at),
 CHECK(observed_at>=scheduled_at AND observed_at<scheduled_at+interval '2 minutes')
);
CREATE TRIGGER preserve_personal_slot_eligibility BEFORE UPDATE ON briefing_personal_slot_eligibility
 FOR EACH ROW EXECUTE FUNCTION preserve_briefing_personal_pool();
