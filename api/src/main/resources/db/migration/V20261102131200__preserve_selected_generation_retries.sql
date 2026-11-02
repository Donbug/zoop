ALTER TABLE briefing_selected_generation_jobs ADD COLUMN attempt_no integer NOT NULL DEFAULT 1 CHECK(attempt_no BETWEEN 1 AND 2);
ALTER TABLE briefing_selected_generation_jobs ADD COLUMN retry_of text REFERENCES briefing_selected_generation_jobs(id) ON DELETE SET NULL;
DO $$ DECLARE constraint_name text; BEGIN
 SELECT conname INTO constraint_name FROM pg_constraint WHERE conrelid='briefing_selected_generation_jobs'::regclass AND contype='u';
 IF constraint_name IS NOT NULL THEN EXECUTE format('ALTER TABLE briefing_selected_generation_jobs DROP CONSTRAINT %I',constraint_name); END IF;
END $$;
ALTER TABLE briefing_selected_generation_jobs ADD CONSTRAINT uq_selected_generation_attempt UNIQUE(member_id,round_id,selection_version,attempt_no);
CREATE OR REPLACE FUNCTION preserve_selected_generation_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.member_id,NEW.round_id,NEW.selection_version,NEW.choice,NEW.request_snapshot,NEW.request_sha256,NEW.attempt_no)
     IS DISTINCT FROM (OLD.member_id,OLD.round_id,OLD.selection_version,OLD.choice,OLD.request_snapshot,OLD.request_sha256,OLD.attempt_no)
 THEN RAISE EXCEPTION 'selected briefing generation scope cannot change'; END IF;
 RETURN NEW;
END $$;
