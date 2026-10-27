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

-- ON DELETE SET NULL updates the execution row, and a receipt-backed row refused every update
-- (V20261014130000, tr_ai_executions_receipt_immutable), so a single such chatbot row would still block the deletion. The
-- one change it now takes is losing a chat job that no longer exists, with nothing else changed: the deletion's own
-- unlinking. Unlinking a job that still exists, or any other change, is refused as before.
CREATE OR REPLACE FUNCTION ai_executions_reject_receipt_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.receipt_artifact_id IS NOT NULL THEN
        IF OLD.feature = 'chatbot' AND OLD.chat_job_id IS NOT NULL AND NEW.chat_job_id IS NULL
            AND to_jsonb(NEW) - 'chat_job_id' = to_jsonb(OLD) - 'chat_job_id'
            AND NOT EXISTS (SELECT 1 FROM chat_jobs j WHERE j.id = OLD.chat_job_id) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'a receipt-backed AI execution is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;
