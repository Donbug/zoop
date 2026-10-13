CREATE TABLE members (
    id text PRIMARY KEY,
    analytics_key text NOT NULL CONSTRAINT uq_members_analytics_key UNIQUE,
    email text NOT NULL,
    email_key text NOT NULL CONSTRAINT uq_members_email_key UNIQUE,
    display_name text NOT NULL,
    signup_method text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    blocked_at timestamptz,
    CONSTRAINT ck_members_signup_method CHECK (signup_method IN ('email', 'google', 'kakao')),
    CONSTRAINT ck_members_status CHECK (status IN ('active', 'blocked'))
);

CREATE TABLE member_credentials (
    member_id text PRIMARY KEY,
    password_hash text NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT fk_member_credentials_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE
);

CREATE TABLE member_sessions (
    id text PRIMARY KEY,
    member_id text,
    kind text NOT NULL,
    analytics_key text,
    token_hash text NOT NULL CONSTRAINT uq_member_sessions_token_hash UNIQUE,
    csrf_key_id text NOT NULL,
    csrf_version bigint NOT NULL,
    tutorial_completed boolean NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT fk_member_sessions_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_member_sessions_kind_and_owner CHECK (
        (kind = 'member' AND member_id IS NOT NULL AND analytics_key IS NULL)
        OR (kind = 'guest' AND member_id IS NULL AND analytics_key IS NOT NULL)
    ),
    CONSTRAINT ck_member_sessions_csrf_version CHECK (csrf_version >= 1)
);

CREATE INDEX ix_member_sessions_active_member_expiry
    ON member_sessions (member_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE INDEX ix_member_sessions_expiry ON member_sessions (expires_at);
