-- Daily web search attempts of the chatbot (web search design 3: 20 per member and 500 for the project per KST day).
-- One row per KST date and subject ('project', or 'member:<id>'), reserved together with the calls in the transaction that
-- reserves them, so concurrent requests cannot both pass the cap. Every reserved web call counts, whether it then succeeded,
-- failed, timed out or never started. A member's rows go with the member.
CREATE TABLE chat_web_search_quotas (
    quota_date date NOT NULL,
    subject_key text NOT NULL,
    member_id text,
    used integer NOT NULL,
    PRIMARY KEY (quota_date, subject_key),
    CONSTRAINT fk_chat_web_search_quotas_member FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_chat_web_search_quotas_subject CHECK (
        (subject_key = 'project' AND member_id IS NULL)
        OR (member_id IS NOT NULL AND subject_key = 'member:' || member_id)),
    CONSTRAINT ck_chat_web_search_quotas_used CHECK (used >= 0)
);
