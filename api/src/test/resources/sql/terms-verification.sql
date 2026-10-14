-- Run against an isolated DB after Flyway; all fixture rows are rolled back.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'btree_gist') THEN
        RAISE EXCEPTION 'btree_gist is missing';
    END IF;
    IF (SELECT count(*) FROM terms WHERE id IN ('service', 'privacy') AND required) <> 2 THEN
        RAISE EXCEPTION 'required term catalog is missing';
    END IF;
    IF (SELECT count(*) FROM term_versions
        WHERE version = '2026-10-13.1'
          AND approved_at = TIMESTAMPTZ '2026-10-13 17:00:00+09'
          AND effective_at = TIMESTAMPTZ '2026-10-13 17:00:00+09'
          AND body !~ '【|배포 금지|미승인 초안') <> 2 THEN
        RAISE EXCEPTION 'approved service/privacy versions are missing or incomplete';
    END IF;
END $$;

INSERT INTO terms (id, title, required, created_at)
VALUES ('test-service', '합성 약관', true, '2026-10-13 00:00:00+00');

INSERT INTO members (
    id, analytics_key, email, email_key, display_name, password_hash,
    signup_method, status, mode, investor, completed, tutorial_completed,
    settings_version, created_at, updated_at
) VALUES (
    'test-member', 'terms-test-analytics', 'terms@example.invalid',
    'terms@example.invalid', '회원', 'synthetic-hash',
    'email', 'active', NULL, NULL, false, false, 1, now(), now()
);

INSERT INTO term_versions (
    term_id, version, title_snapshot, required_snapshot, body,
    approved_at, effective_at, retired_at
) VALUES (
    'test-service', 'v1', '합성 약관', true, '테스트 본문',
    '2026-10-13 00:00:00+00', '2026-10-14 00:00:00+00',
    '2026-10-15 00:00:00+00'
);

-- Adjacent half-open effective periods are allowed.
INSERT INTO term_versions (
    term_id, version, title_snapshot, required_snapshot, body,
    approved_at, effective_at
) VALUES (
    'test-service', 'v2', '합성 약관', true, '테스트 본문 2',
    '2026-10-13 00:00:00+00', '2026-10-15 00:00:00+00'
);

INSERT INTO term_agreements (
    member_id, term_id, term_version, accepted, accepted_at
) VALUES ('test-member', 'test-service', 'v1', true, now());

DO $$
BEGIN
    BEGIN
        INSERT INTO term_versions (
            term_id, version, title_snapshot, required_snapshot, body,
            approved_at, effective_at
        ) VALUES (
            'test-service', 'overlap', '합성 약관', true, '중복 본문',
            '2026-10-13 00:00:00+00', '2026-10-14 12:00:00+00'
        );
        RAISE EXCEPTION 'overlapping version period was accepted';
    EXCEPTION WHEN exclusion_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO term_versions (
            term_id, version, title_snapshot, required_snapshot, body,
            approved_at, effective_at
        ) VALUES (
            'test-service', 'unapproved', '합성 약관', true, '본문',
            '2026-10-16 00:00:00+00', '2026-10-15 00:00:00+00'
        );
        RAISE EXCEPTION 'approval after effectiveness was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO term_agreements (
            member_id, term_id, term_version, accepted, accepted_at
        ) VALUES ('missing-member', 'test-service', 'v1', true, now());
        RAISE EXCEPTION 'unknown member agreement was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO term_agreements (
            member_id, term_id, term_version, accepted, accepted_at
        ) VALUES ('test-member', 'test-service', 'missing-version', true, now());
        RAISE EXCEPTION 'unknown term version agreement was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END $$;

ROLLBACK;
