CREATE TABLE admins (
    id text PRIMARY KEY,
    email text NOT NULL,
    email_key text NOT NULL CONSTRAINT uq_admins_email_key UNIQUE,
    display_name text NOT NULL,
    password_hash text,
    external_subject text CONSTRAINT uq_admins_external_subject UNIQUE,
    role text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT ck_admins_identity CHECK (
        password_hash IS NOT NULL OR external_subject IS NOT NULL
    ),
    CONSTRAINT ck_admins_role CHECK (role = 'admin'),
    CONSTRAINT ck_admins_status CHECK (status IN ('active', 'blocked'))
);

CREATE TABLE admin_sessions (
    id text PRIMARY KEY,
    admin_id text NOT NULL,
    token_hash char(64) NOT NULL CONSTRAINT uq_admin_sessions_token_hash UNIQUE,
    csrf_key_id text NOT NULL,
    csrf_version bigint NOT NULL,
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    idle_expires_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT fk_admin_sessions_admin
        FOREIGN KEY (admin_id) REFERENCES admins (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_admin_sessions_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_admin_sessions_csrf_version CHECK (csrf_version >= 1),
    CONSTRAINT ck_admin_sessions_lifecycle CHECK (
        created_at <= last_seen_at
        AND last_seen_at < idle_expires_at
        AND idle_expires_at <= expires_at
        AND (revoked_at IS NULL OR revoked_at >= created_at)
    )
);

CREATE INDEX ix_admin_sessions_active_admin_expiry
    ON admin_sessions (admin_id, expires_at)
    WHERE revoked_at IS NULL;
CREATE INDEX ix_admin_sessions_expiry ON admin_sessions (expires_at);

CREATE TABLE audit_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_kind text NOT NULL,
    admin_id text,
    actor_id text NOT NULL,
    actor_email_snapshot text,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id text,
    outcome text NOT NULL,
    purpose text,
    reason text,
    request_id text NOT NULL,
    detail jsonb NOT NULL,
    occurred_at timestamptz NOT NULL,
    CONSTRAINT fk_audit_logs_admin
        FOREIGN KEY (admin_id) REFERENCES admins (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_audit_logs_actor CHECK (
        (actor_kind = 'admin' AND admin_id IS NOT NULL AND actor_id = admin_id)
        OR (actor_kind IN ('anonymous', 'system') AND admin_id IS NULL)
    ),
    CONSTRAINT ck_audit_logs_outcome CHECK (outcome IN ('succeeded', 'denied', 'failed')),
    CONSTRAINT ck_audit_logs_detail_object CHECK (jsonb_typeof(detail) = 'object')
);

CREATE INDEX ix_audit_logs_occurred_at ON audit_logs (occurred_at DESC, id DESC);
CREATE INDEX ix_audit_logs_target ON audit_logs (target_type, target_id, occurred_at DESC);

ALTER TABLE auth_rate_events DROP CONSTRAINT ck_auth_rate_events_scope;
ALTER TABLE auth_rate_events ADD CONSTRAINT ck_auth_rate_events_scope CHECK (scope IN (
    'signup_ip', 'signup_email', 'login_ip', 'login_email_failure',
    'social_start_ip', 'social_start_browser', 'admin_login_ip', 'admin_login_email_failure'
));
