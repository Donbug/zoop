-- The verified result of a chatbot attempt, kept before it is stored on the job (ZOOP-AIG-001 6.3.4: a result that was verified
-- but could not be saved is saved again with no model call). One immutable row per attempt, written in its own transaction under
-- the run's owner fence. The row goes when the job ends any other way than save_failed, and with the job.
CREATE TABLE chat_recovery_results (
    chat_job_id text NOT NULL,
    attempt_no integer NOT NULL,
    result jsonb NOT NULL,
    route_summary jsonb,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (chat_job_id, attempt_no),
    CONSTRAINT fk_chat_recovery_results_job FOREIGN KEY (chat_job_id) REFERENCES chat_jobs (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_chat_recovery_results_attempt CHECK (attempt_no >= 1)
);
