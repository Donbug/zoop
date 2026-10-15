ALTER TABLE member_sessions
    DROP CONSTRAINT ck_member_sessions_kind_and_owner,
    ADD CONSTRAINT ck_member_sessions_kind_and_owner CHECK (
        (kind = 'member' AND member_id IS NOT NULL
            AND analytics_key IS NULL AND auth_flow IS NULL)
        OR (kind = 'guest' AND member_id IS NULL
            AND analytics_key IS NOT NULL AND auth_flow IS NULL
            AND tutorial_completed = false)
        OR (kind = 'oauth_pending' AND member_id IS NULL
            AND analytics_key IS NULL AND auth_flow IS NOT NULL
            AND tutorial_completed = false)
    );
