-- FS066: saved result identities only; no prompt, question, answer or article body is copied.
CREATE TABLE ai_result_feedback (
    id text PRIMARY KEY,
    member_id text NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    feature text NOT NULL CHECK(feature IN ('chatbot_answer','news_summary')),
    target_id text NOT NULL CHECK(btrim(target_id)<>''),
    target_version text NOT NULL CHECK(btrim(target_version)<>''),
    chat_job_id text REFERENCES chat_jobs(id) ON DELETE CASCADE,
    evidence_id text REFERENCES evidence(id) ON DELETE CASCADE,
    value text NOT NULL CHECK(value IN ('up','down','none')),
    reason text CHECK(reason IS NULL OR (value='down' AND char_length(reason)<=200)),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK(updated_at>=created_at),
    UNIQUE(member_id,feature,target_id),
    CHECK((feature='chatbot_answer' AND chat_job_id IS NOT NULL AND evidence_id IS NULL)
       OR (feature='news_summary' AND chat_job_id IS NULL AND evidence_id=target_id))
);
CREATE INDEX ix_ai_result_feedback_updated ON ai_result_feedback(updated_at DESC,id DESC);
