-- Historical receipt collection is distinct from a generation attempt. Unknown original starts remain NULL.
ALTER TABLE briefing_attempts DROP CONSTRAINT briefing_attempts_purpose_check;
ALTER TABLE briefing_attempts ADD CONSTRAINT briefing_attempts_purpose_check CHECK(purpose IN ('generation','outlook','history'));
ALTER TABLE briefing_attempts ALTER COLUMN started_at DROP NOT NULL;
ALTER TABLE briefing_attempts ADD CONSTRAINT ck_briefing_runtime_start CHECK(purpose='history' OR started_at IS NOT NULL);
ALTER TABLE ai_executions ADD COLUMN recording_origin text NOT NULL DEFAULT 'runtime' CHECK(recording_origin IN ('runtime','archive'));
ALTER TABLE ai_executions ALTER COLUMN started_at DROP NOT NULL;
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_runtime_start CHECK(recording_origin='archive' OR started_at IS NOT NULL);
