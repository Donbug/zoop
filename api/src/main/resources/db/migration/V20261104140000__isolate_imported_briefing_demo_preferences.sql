-- Existing preferences stay scheduled and retain their original values. New archived
-- demo preferences have their own revision sequence and never become live settings.
ALTER TABLE briefing_personal_preferences
 ADD COLUMN scope text NOT NULL DEFAULT 'scheduled' CHECK (scope IN ('scheduled','demo'));
ALTER TABLE briefing_personal_preferences
 DROP CONSTRAINT briefing_personal_preferences_member_id_revision_key;
ALTER TABLE briefing_personal_preferences
 ADD CONSTRAINT personal_preference_scoped_revision UNIQUE(member_id,scope,revision);

CREATE FUNCTION require_scheduled_preference_scope() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.mode='scheduled' AND NOT EXISTS (
   SELECT 1 FROM briefing_personal_preferences p
   WHERE p.id=NEW.preference_id AND p.member_id=NEW.member_id AND p.scope='scheduled'
 ) THEN RAISE EXCEPTION 'scheduled delivery requires scheduled preference'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER personal_delivery_preference_scope BEFORE INSERT OR UPDATE ON briefing_personal_deliveries
 FOR EACH ROW EXECUTE FUNCTION require_scheduled_preference_scope();

-- Idempotency/provenance for an explicit operator import of saved results. No AI
-- execution, scheduler run or historical operational generation is invented.
CREATE TABLE briefing_result_imports (
 request_sha256 text PRIMARY KEY CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
 manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[0-9a-f]{64}$'),
 member_id text NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 round_ids jsonb NOT NULL CHECK(jsonb_typeof(round_ids)='array'),
 applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER preserve_briefing_result_import BEFORE UPDATE ON briefing_result_imports
 FOR EACH ROW EXECUTE FUNCTION preserve_briefing_personal_pool();
