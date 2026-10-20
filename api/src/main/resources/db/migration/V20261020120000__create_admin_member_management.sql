ALTER TABLE members
    ADD COLUMN status_revision bigint NOT NULL DEFAULT 1,
    ADD CONSTRAINT ck_members_status_revision CHECK (status_revision >= 1);

CREATE TABLE idempotency_records (
    id text PRIMARY KEY,
    principal_kind text NOT NULL,
    principal_id text NOT NULL,
    method text NOT NULL,
    path text NOT NULL,
    idem_key text NOT NULL,
    request_hash char(64) NOT NULL,
    status text NOT NULL,
    resource_type text,
    resource_id text,
    owner_token text,
    lease_until timestamptz,
    response_status integer,
    response_body jsonb,
    created_at timestamptz NOT NULL,
    expires_at timestamptz,
    CONSTRAINT uq_idempotency_scope
        UNIQUE (principal_kind, principal_id, method, path, idem_key),
    CONSTRAINT ck_idempotency_principal_kind
        CHECK (principal_kind IN ('member', 'guest', 'admin', 'anonymous')),
    CONSTRAINT ck_idempotency_method CHECK (method = 'POST'),
    CONSTRAINT ck_idempotency_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_idempotency_status CHECK (status IN ('processing', 'completed', 'failed')),
    CONSTRAINT ck_idempotency_completion CHECK (
        (status = 'processing' AND response_status IS NULL AND response_body IS NULL)
        OR (status IN ('completed', 'failed') AND response_status IS NOT NULL AND response_body IS NOT NULL)
    ),
    CONSTRAINT ck_idempotency_key_length CHECK (length(idem_key) BETWEEN 1 AND 200),
    CONSTRAINT ck_idempotency_path CHECK (length(path) > 0),
    CONSTRAINT ck_idempotency_lifecycle CHECK (
        (owner_token IS NULL) = (lease_until IS NULL)
        AND (expires_at IS NULL OR expires_at > created_at)
    )
);

CREATE INDEX ix_idempotency_expiry
    ON idempotency_records (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE INDEX ix_members_admin_list
    ON members (created_at DESC, id DESC);

CREATE INDEX ix_members_admin_status_list
    ON members (status, created_at DESC, id DESC);
