-- FS068 / A-ADM-04b: preserve which chat-job attempt made each model call and whether the provider received it.
ALTER TABLE ai_executions ADD COLUMN provider_send_state text;
ALTER TABLE ai_executions ADD COLUMN provider_revision text;
ALTER TABLE ai_executions ADD COLUMN receipt_execution_mode text;
ALTER TABLE ai_executions ADD COLUMN provider_sent_at timestamptz;
ALTER TABLE ai_executions ADD COLUMN provider_received_at timestamptz;
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_executions_provider_send_state
    CHECK (provider_send_state IS NULL OR provider_send_state IN ('sent', 'not_sent', 'unknown'));
CREATE INDEX ix_ai_executions_chat_attempt ON ai_executions (chat_job_id, attempt_no, started_at)
    WHERE chat_job_id IS NOT NULL;
