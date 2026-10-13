-- V20261012210200 is already published. This migration targets the empty
-- auth schema; fail rather than discard unexpected data from another DB.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM members)
        OR EXISTS (SELECT 1 FROM member_credentials)
        OR EXISTS (SELECT 1 FROM member_sessions) THEN
        RAISE EXCEPTION 'ERD v6 auth migration requires empty auth tables';
    END IF;
END $$;

ALTER TABLE members
    ADD COLUMN password_hash text,
    ADD COLUMN mode text NOT NULL,
    ADD COLUMN investor boolean,
    ADD COLUMN completed boolean NOT NULL,
    ADD COLUMN tutorial_completed boolean NOT NULL,
    ADD COLUMN settings_version bigint NOT NULL,
    ADD COLUMN updated_at timestamptz NOT NULL,
    ADD CONSTRAINT ck_members_email_password_hash
        CHECK (signup_method <> 'email' OR password_hash IS NOT NULL),
    ADD CONSTRAINT ck_members_mode
        CHECK (mode IN ('assets', 'watchlist')),
    ADD CONSTRAINT ck_members_settings_version
        CHECK (settings_version >= 1);

DROP TABLE member_credentials;

ALTER TABLE member_sessions
    ADD COLUMN auth_flow jsonb,
    DROP CONSTRAINT ck_member_sessions_kind_and_owner,
    ADD CONSTRAINT ck_member_sessions_kind_and_owner CHECK (
        (kind = 'member' AND member_id IS NOT NULL
            AND analytics_key IS NULL AND auth_flow IS NULL)
        OR (kind = 'guest' AND member_id IS NULL
            AND analytics_key IS NOT NULL AND auth_flow IS NULL)
        OR (kind = 'oauth_pending' AND member_id IS NULL
            AND analytics_key IS NULL AND auth_flow IS NOT NULL
            AND tutorial_completed = false)
    );

CREATE INDEX ix_member_sessions_member_created_at
    ON member_sessions (member_id, created_at);
