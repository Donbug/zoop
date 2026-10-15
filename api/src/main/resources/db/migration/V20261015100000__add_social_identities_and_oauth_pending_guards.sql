CREATE TABLE social_identities (
    id text PRIMARY KEY,
    member_id text NOT NULL,
    provider text NOT NULL,
    provider_subject text NOT NULL,
    linked_at timestamptz NOT NULL,
    CONSTRAINT fk_social_identities_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_social_identities_provider
        CHECK (provider IN ('google', 'kakao')),
    CONSTRAINT ck_social_identities_provider_subject
        CHECK (length(provider_subject) BETWEEN 1 AND 512),
    CONSTRAINT uq_social_identities_provider_subject
        UNIQUE (provider, provider_subject)
);

CREATE INDEX ix_social_identities_member_linked_at
    ON social_identities (member_id, linked_at DESC, id);

ALTER TABLE member_sessions
    ADD CONSTRAINT ck_member_sessions_oauth_flow_object
        CHECK (
            kind <> 'oauth_pending'
            OR (
                jsonb_typeof(auth_flow) = 'object'
                AND auth_flow ?& ARRAY['schemaVersion', 'phase', 'provider', 'stateHash']
                AND jsonb_typeof(auth_flow->'schemaVersion') = 'number'
                AND jsonb_typeof(auth_flow->'phase') = 'string'
                AND jsonb_typeof(auth_flow->'provider') = 'string'
                AND jsonb_typeof(auth_flow->'stateHash') = 'string'
                AND auth_flow->>'schemaVersion' = '1'
                AND auth_flow->>'phase' IN (
                    'authorization_pending', 'callback_processing', 'identity_verified', 'consent_pending'
                )
                AND auth_flow->>'provider' IN ('google', 'kakao')
                AND auth_flow->>'stateHash' ~ '^[0-9a-f]{64}$'
            )
        );

CREATE INDEX ix_member_sessions_oauth_pending_expiry
    ON member_sessions (expires_at)
    WHERE kind = 'oauth_pending';
