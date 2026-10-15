-- Run against an isolated database after Flyway has applied the auth migrations.
-- The transaction is rolled back so the fixture never becomes development data.
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.member_credentials') IS NOT NULL THEN
        RAISE EXCEPTION 'member_credentials must be removed';
    END IF;
    IF (
        SELECT count(*) FROM flyway_schema_history
        WHERE success AND version IN ('20261012210200', '20261013000000', '20261014140000', '20261015100000', '20261015110000')
    ) <> 5 THEN
        RAISE EXCEPTION 'expected all five required auth migrations';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'member_sessions'
          AND indexname = 'ix_member_sessions_member_created_at'
    ) THEN
        RAISE EXCEPTION 'member session creation index is missing';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'member_sessions'
          AND indexname = 'ix_member_sessions_oauth_pending_expiry'
    ) THEN
        RAISE EXCEPTION 'OAuth pending expiry index is missing';
    END IF;
END $$;

INSERT INTO members (
    id, analytics_key, email, email_key, display_name, password_hash,
    signup_method, status, mode, investor, completed, tutorial_completed,
    settings_version, created_at, updated_at
) VALUES
    ('test-email', 'ak-email', 'email@example.invalid', 'email@example.invalid',
     '회원', 'synthetic-hash', 'email', 'active', 'assets', NULL, false, false,
     1, now(), now()),
    ('test-social', 'ak-social', 'social@example.invalid', 'social@example.invalid',
     '회원', NULL, 'google', 'active', 'watchlist', NULL, false, false,
     1, now(), now());

INSERT INTO social_identities (id, member_id, provider, provider_subject, linked_at)
VALUES ('test-social-identity', 'test-social', 'google', 'synthetic-google-subject', now());

INSERT INTO member_sessions (
    id, member_id, kind, analytics_key, token_hash, csrf_key_id, csrf_version,
    tutorial_completed, auth_flow, created_at, expires_at
) VALUES
    ('test-member-session', 'test-email', 'member', NULL, 'hash-member', 'key', 1,
     false, NULL, now(), now() + interval '1 day'),
    ('test-guest-session', NULL, 'guest', 'guest-analytics', 'hash-guest', 'key', 1,
     false, NULL, now(), now() + interval '1 day'),
    ('test-oauth-session', NULL, 'oauth_pending', NULL, 'hash-oauth', 'reserved', 1,
     false, jsonb_build_object('schemaVersion', 1, 'phase', 'authorization_pending',
        'provider', 'google', 'stateHash', repeat('a', 64)), now(), now() + interval '5 minutes'),
    ('test-oauth-verified', NULL, 'oauth_pending', NULL, 'hash-oauth-verified', 'reserved', 1,
     false, jsonb_build_object('schemaVersion', 1, 'phase', 'identity_verified',
        'provider', 'kakao', 'stateHash', repeat('b', 64), 'providerSubject', 'synthetic-subject',
        'email', 'verified@example.invalid', 'emailVerified', true), now(), now() + interval '5 minutes');

DO $$
BEGIN
    BEGIN
        INSERT INTO members (
            id, analytics_key, email, email_key, display_name, signup_method,
            status, mode, completed, tutorial_completed, settings_version,
            created_at, updated_at
        ) VALUES (
            'bad-password', 'bad-ak-1', 'bad1@example.invalid', 'bad1@example.invalid',
            '회원', 'email', 'active', 'assets', false, false, 1, now(), now()
        );
        RAISE EXCEPTION 'email member without password hash was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO members (
            id, analytics_key, email, email_key, display_name, password_hash,
            signup_method, status, mode, completed, tutorial_completed,
            settings_version, created_at, updated_at
        ) VALUES (
            'bad-mode', 'bad-ak-2', 'bad2@example.invalid', 'bad2@example.invalid',
            '회원', 'synthetic-hash', 'email', 'active', 'invalid', false, false,
            1, now(), now()
        );
        RAISE EXCEPTION 'invalid mode was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO members (
            id, analytics_key, email, email_key, display_name, password_hash,
            signup_method, status, mode, completed, tutorial_completed,
            settings_version, created_at, updated_at
        ) VALUES (
            'bad-version', 'bad-ak-3', 'bad3@example.invalid', 'bad3@example.invalid',
            '회원', 'synthetic-hash', 'email', 'active', 'assets', false, false,
            0, now(), now()
        );
        RAISE EXCEPTION 'settings version zero was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO member_sessions (
            id, member_id, kind, token_hash, csrf_key_id, csrf_version,
            tutorial_completed, auth_flow, created_at, expires_at
        ) VALUES (
            'bad-member-flow', 'test-email', 'member', 'bad-hash-1', 'key', 1,
            false, '{}'::jsonb, now(), now() + interval '1 day'
        );
        RAISE EXCEPTION 'member session with auth_flow was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO member_sessions (
            id, kind, token_hash, csrf_key_id, csrf_version,
            tutorial_completed, created_at, expires_at
        ) VALUES (
            'bad-guest-owner', 'guest', 'bad-hash-2', 'key', 1,
            false, now(), now() + interval '1 day'
        );
        RAISE EXCEPTION 'guest session without analytics key was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO member_sessions (
            id, member_id, kind, token_hash, csrf_key_id, csrf_version,
            tutorial_completed, auth_flow, created_at, expires_at
        ) VALUES (
            'bad-oauth-owner', 'test-email', 'oauth_pending', 'bad-hash-3', 'key', 1,
            false, '{}'::jsonb, now(), now() + interval '1 day'
        );
        RAISE EXCEPTION 'oauth pending session with member was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO member_sessions (
            id, kind, token_hash, csrf_key_id, csrf_version,
            tutorial_completed, auth_flow, created_at, expires_at
        ) VALUES (
            'bad-oauth-tutorial', 'oauth_pending', 'bad-hash-4', 'key', 1,
            true, '{}'::jsonb, now(), now() + interval '1 day'
        );
        RAISE EXCEPTION 'oauth pending session with tutorial access was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO social_identities (id, member_id, provider, provider_subject, linked_at)
        VALUES ('bad-social-identity', 'test-email', 'google', 'synthetic-google-subject', now());
        RAISE EXCEPTION 'duplicate provider subject was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO member_sessions (
            id, kind, token_hash, csrf_key_id, csrf_version,
            tutorial_completed, auth_flow, created_at, expires_at
        ) VALUES (
            'bad-oauth-flow', 'oauth_pending', 'bad-hash-5', 'reserved', 1,
            false, '{}'::jsonb, now(), now() + interval '5 minutes'
        );
        RAISE EXCEPTION 'invalid oauth flow document was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

ROLLBACK;
