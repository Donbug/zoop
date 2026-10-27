-- A conversation deleted by its member, or with the member's account, takes its chat jobs and tool calls with it (privacy
-- policy 2026-10-13.1: conversations are destroyed on withdrawal, no long-term backup). Until now `ai_executions` held its
-- chat job with ON DELETE RESTRICT, so once a question had called a model neither its conversation nor its member could be
-- deleted.
--
-- A chatbot execution row holds no question, answer or member id: stage, model, tokens, cost and times. It now outlives the
-- job it belonged to, with `chat_job_id` set to null, so the cost and usage totals stay whole. Rows of the other features
-- still need their owner.

ALTER TABLE ai_executions DROP CONSTRAINT fk_ai_executions_chat_job;
ALTER TABLE ai_executions ADD CONSTRAINT fk_ai_executions_chat_job FOREIGN KEY (chat_job_id) REFERENCES chat_jobs (id)
    ON UPDATE RESTRICT ON DELETE SET NULL;

ALTER TABLE ai_executions DROP CONSTRAINT ck_ai_executions_owner;
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_executions_owner CHECK (
    num_nonnulls(chat_job_id, briefing_attempt_id, analysis_job_id, document_analysis_id) >= 1 OR feature = 'chatbot');
