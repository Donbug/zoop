-- Run against an isolated DB after Flyway (psql -X -v ON_ERROR_STOP=1); every fixture row is rolled back, so the script
-- can also run on the database an import smoke just used. It proves the ERD v6 section 14-16 constraints, the
-- immutability triggers and the exact compare-and-set statement the importer uses.
BEGIN;

DO $$
BEGIN
    IF (SELECT count(*) FROM flyway_schema_history WHERE version = '20261014120000' AND success) <> 1 THEN
        RAISE EXCEPTION 'document registry migration is not recorded as applied';
    END IF;
    IF (SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema() AND indexname IN
        ('ux_articles_provider_key', 'ix_article_versions_collected', 'ix_article_versions_published_at',
         'uq_artifacts_storage_uri')) <> 4 THEN
        RAISE EXCEPTION 'document registry indexes are missing';
    END IF;
    IF (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN
        ('tr_artifacts_immutable', 'tr_article_versions_immutable', 'tr_articles_identity_immutable')) <> 3 THEN
        RAISE EXCEPTION 'document registry immutability triggers are missing';
    END IF;
END $$;

INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at) VALUES
    ('proof-text-a', 'extracted_text', 'artifact-root:extracted_text/proof-a.txt', repeat('a', 64), 10,
     'text/plain; charset=utf-8', now()),
    -- Equal bytes under another identity are allowed: only the URI is unique.
    ('proof-text-b', 'extracted_text', 'artifact-root:extracted_text/proof-b.txt', repeat('a', 64), 10,
     'text/plain; charset=utf-8', now()),
    ('proof-text-c', 'extracted_text', 'artifact-root:extracted_text/proof-c.txt', repeat('c', 64), 0,
     'text/plain; charset=utf-8', now());

INSERT INTO articles (id, kind, provider, provider_key, lineage_key, current_version, access_status, created_at) VALUES
    ('proof-article-a', 'news', 'proof-source', NULL, NULL, NULL, 'available', now()),
    ('proof-article-b', 'disclosure', 'proof-source', NULL, NULL, NULL, 'available', now()),
    ('proof-article-k1', 'news', 'proof-source', 'key-1', NULL, NULL, 'available', now());

INSERT INTO article_versions (article_id, version, title, publisher, url, published_at, published_date,
                              publication_precision, raw_artifact_id, text_artifact_id, collected_at) VALUES
    ('proof-article-a', 'va1', '', NULL, 'https://example.invalid/a', '2026-10-08 00:00:00+00', NULL, 'datetime',
     NULL, 'proof-text-a', '2026-10-09 00:00:00+00'),
    ('proof-article-a', 'va2', 'title', NULL, NULL, NULL, NULL, 'unknown', NULL, 'proof-text-c',
     '2026-10-10 00:00:00+00'),
    ('proof-article-a', 'vday', NULL, NULL, NULL, NULL, DATE '2026-10-08', 'day', NULL, 'proof-text-c',
     '2026-10-10 00:00:00+00'),
    ('proof-article-b', 'vb1', 'b', NULL, NULL, NULL, NULL, 'unknown', NULL, 'proof-text-b', '2026-10-09 00:00:00+00');

DO $$
DECLARE
    changed integer;
BEGIN
    -- artifacts
    BEGIN
        INSERT INTO artifacts VALUES ('proof-bad-kind', 'other', 'artifact-root:x/1', repeat('a', 64), 1, 'text/plain', now());
        RAISE EXCEPTION 'unknown artifact kind was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO artifacts VALUES ('proof-bad-bytes', 'extracted_text', 'artifact-root:x/2', repeat('a', 64), -1,
            'text/plain', now());
        RAISE EXCEPTION 'negative artifact size was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO artifacts VALUES ('proof-bad-sha', 'extracted_text', 'artifact-root:x/3', repeat('A', 64), 1,
            'text/plain', now());
        RAISE EXCEPTION 'uppercase sha256 was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO artifacts VALUES ('proof-short-sha', 'extracted_text', 'artifact-root:x/4', repeat('a', 63), 1,
            'text/plain', now());
        RAISE EXCEPTION 'short sha256 was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO artifacts VALUES ('proof-same-uri', 'extracted_text', 'artifact-root:extracted_text/proof-a.txt',
            repeat('b', 64), 1, 'text/plain', now());
        RAISE EXCEPTION 'duplicate storage URI was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    -- The importer's idempotent insert: an existing id is left alone, a taken URI under a new id is an error.
    INSERT INTO artifacts VALUES ('proof-text-a', 'extracted_text', 'artifact-root:extracted_text/other.txt', repeat('f', 64),
        99, 'text/plain', now()) ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 0 OR (SELECT storage_uri FROM artifacts WHERE id = 'proof-text-a')
        <> 'artifact-root:extracted_text/proof-a.txt' THEN
        RAISE EXCEPTION 'ON CONFLICT DO NOTHING modified or duplicated an artifact';
    END IF;

    -- articles
    BEGIN
        INSERT INTO articles (id, kind, provider, access_status, created_at)
        VALUES ('proof-bad-article-kind', 'blog', 'proof-source', 'available', now());
        RAISE EXCEPTION 'unknown article kind was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO articles (id, kind, provider, access_status, created_at)
        VALUES ('proof-bad-access', 'news', 'proof-source', 'hidden', now());
        RAISE EXCEPTION 'unknown access status was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO articles (id, kind, provider, provider_key, access_status, created_at)
        VALUES ('proof-article-k2', 'news', 'proof-source', 'key-1', 'available', now());
        RAISE EXCEPTION 'duplicate provider key was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    -- The same key under another provider, and any number of NULL keys, are allowed.
    INSERT INTO articles (id, kind, provider, provider_key, access_status, created_at) VALUES
        ('proof-article-k3', 'news', 'proof-other-source', 'key-1', 'available', now()),
        ('proof-article-n1', 'news', 'proof-source', NULL, 'available', now()),
        ('proof-article-n2', 'news', 'proof-source', NULL, 'available', now());
    INSERT INTO articles (id, kind, provider, access_status, created_at)
    VALUES ('proof-article-a', 'disclosure', 'other', 'available', now()) ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 0 OR (SELECT kind FROM articles WHERE id = 'proof-article-a') <> 'news' THEN
        RAISE EXCEPTION 'ON CONFLICT DO NOTHING modified or duplicated an article';
    END IF;

    -- article_versions: publication triplet
    BEGIN
        INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at)
        VALUES ('proof-article-a', 'bad1', 'datetime', 'proof-text-a', now());
        RAISE EXCEPTION 'datetime precision without published_at was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, published_at, publication_precision, text_artifact_id,
                                      collected_at)
        VALUES ('proof-article-a', 'bad2', now(), 'unknown', 'proof-text-a', now());
        RAISE EXCEPTION 'unknown precision with published_at was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, published_at, published_date, publication_precision,
                                      text_artifact_id, collected_at)
        VALUES ('proof-article-a', 'bad3', now(), DATE '2026-10-08', 'datetime', 'proof-text-a', now());
        RAISE EXCEPTION 'datetime precision with published_date was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, published_at, publication_precision, text_artifact_id,
                                      collected_at)
        VALUES ('proof-article-a', 'bad4', now(), 'day', 'proof-text-a', now());
        RAISE EXCEPTION 'day precision with published_at was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at)
        VALUES ('proof-article-a', 'bad5', 'hour', 'proof-text-a', now());
        RAISE EXCEPTION 'unknown precision value was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    -- article_versions: references
    BEGIN
        INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at)
        VALUES ('proof-missing-article', 'v1', 'unknown', 'proof-text-a', now());
        RAISE EXCEPTION 'version of an unknown article was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at)
        VALUES ('proof-article-a', 'bad6', 'unknown', 'proof-missing-artifact', now());
        RAISE EXCEPTION 'version of an unknown text artifact was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, publication_precision, raw_artifact_id, text_artifact_id,
                                      collected_at)
        VALUES ('proof-article-a', 'bad7', 'unknown', 'proof-missing-artifact', 'proof-text-a', now());
        RAISE EXCEPTION 'version of an unknown raw artifact was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at)
        VALUES ('proof-article-a', 'va1', 'unknown', 'proof-text-a', now());
        RAISE EXCEPTION 'duplicate (article, version) was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at)
    VALUES ('proof-article-a', 'va1', 'unknown', 'proof-text-c', '2030-01-01 00:00:00+00')
    ON CONFLICT (article_id, version) DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 0 OR (SELECT collected_at FROM article_versions WHERE article_id = 'proof-article-a' AND version = 'va1')
        <> TIMESTAMPTZ '2026-10-09 00:00:00+00' THEN
        RAISE EXCEPTION 'ON CONFLICT DO NOTHING changed the first registered observation';
    END IF;

    -- The importer's compare-and-set: NULL-safe, exact, never a silent overwrite.
    UPDATE articles SET current_version = 'va1'
    WHERE id = 'proof-article-a' AND current_version IS NOT DISTINCT FROM CAST(NULL AS text);
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 1 THEN
        RAISE EXCEPTION 'compare-and-set from an unset pointer did not move it';
    END IF;
    UPDATE articles SET current_version = 'va2'
    WHERE id = 'proof-article-a' AND current_version IS NOT DISTINCT FROM CAST(NULL AS text);
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 0 OR (SELECT current_version FROM articles WHERE id = 'proof-article-a') <> 'va1' THEN
        RAISE EXCEPTION 'compare-and-set with a stale NULL expectation moved the pointer';
    END IF;
    UPDATE articles SET current_version = 'va2'
    WHERE id = 'proof-article-a' AND current_version IS NOT DISTINCT FROM CAST('va1' AS text);
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 1 OR (SELECT current_version FROM articles WHERE id = 'proof-article-a') <> 'va2' THEN
        RAISE EXCEPTION 'compare-and-set with the exact expectation did not move the pointer';
    END IF;

    -- pointer constraints: composite FK to a version of the same article
    BEGIN
        UPDATE articles SET current_version = 'missing-version' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'pointer to a missing version was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE articles SET current_version = 'vb1' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'pointer to another article''s version was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    -- access_status and current_version are the only mutable article columns.
    UPDATE articles SET access_status = 'private' WHERE id = 'proof-article-a';
    UPDATE articles SET access_status = 'deleted' WHERE id = 'proof-article-a';
    UPDATE articles SET access_status = 'available', current_version = NULL WHERE id = 'proof-article-a';
    BEGIN
        UPDATE articles SET kind = 'disclosure' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article kind update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE articles SET provider = 'moved' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article provider update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE articles SET provider_key = 'late-key' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article provider key update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE articles SET lineage_key = 'lineage' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article lineage key update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE articles SET created_at = now() + interval '1 day' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article creation time update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE articles SET id = 'proof-article-renamed' WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article id update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;

    -- immutable rows
    BEGIN
        UPDATE artifacts SET storage_uri = 'artifact-root:extracted_text/overwritten.txt' WHERE id = 'proof-text-a';
        RAISE EXCEPTION 'artifact URI overwrite was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE artifacts SET sha256 = repeat('e', 64) WHERE id = 'proof-text-a';
        RAISE EXCEPTION 'artifact hash update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE article_versions SET title = 'changed' WHERE article_id = 'proof-article-a' AND version = 'va1';
        RAISE EXCEPTION 'article version title update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;
    BEGIN
        UPDATE article_versions SET collected_at = now() WHERE article_id = 'proof-article-a' AND version = 'va1';
        RAISE EXCEPTION 'article version collected_at update was accepted';
    EXCEPTION WHEN restrict_violation THEN NULL;
    END;

    -- RESTRICT deletes
    BEGIN
        DELETE FROM articles WHERE id = 'proof-article-a';
        RAISE EXCEPTION 'article with versions was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    UPDATE articles SET current_version = 'va1' WHERE id = 'proof-article-a';
    BEGIN
        DELETE FROM article_versions WHERE article_id = 'proof-article-a' AND version = 'va1';
        RAISE EXCEPTION 'current version was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM artifacts WHERE id = 'proof-text-a';
        RAISE EXCEPTION 'referenced artifact was deleted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END $$;

ROLLBACK;
