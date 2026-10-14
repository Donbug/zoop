CREATE TABLE auth_rate_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope text NOT NULL,
    subject_hash char(64) NOT NULL,
    occurred_at timestamptz NOT NULL,
    CONSTRAINT ck_auth_rate_events_scope CHECK (scope IN (
        'signup_ip', 'signup_email', 'login_ip', 'login_email_failure'))
);

CREATE INDEX ix_auth_rate_events_subject_time
    ON auth_rate_events (scope, subject_hash, occurred_at);
CREATE INDEX ix_auth_rate_events_time ON auth_rate_events (occurred_at);
