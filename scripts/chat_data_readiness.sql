\set ON_ERROR_STOP on

-- Content-free inventory for the chatbot's real-data readiness gate. It returns ids, counts and immutable artifact
-- metadata only: no member, question, answer, quote, document body, credential or path outside registered artifact URIs.
WITH graph_payload AS (
    SELECT v.id, v.sequence, v.kind, v.active, v.published_at, v.issue_count, v.relation_count, v.article_count,
           jsonb_build_object(
               'storageUri', snapshot.storage_uri,
               'sha256', snapshot.sha256,
               'bytes', snapshot.bytes
           ) AS snapshot,
           COALESCE((
               SELECT jsonb_agg(item ORDER BY item->>'role', (item->>'ordinal')::integer)
               FROM (
                   SELECT jsonb_build_object(
                       'role', 'receipt', 'ordinal', source.ordinal,
                       'storageUri', receipt.storage_uri, 'sha256', receipt.sha256, 'bytes', receipt.bytes
                   ) AS item
                   FROM graph_version_sources source
                   JOIN artifacts receipt ON receipt.id = source.receipt_artifact_id
                   WHERE source.graph_version_id = v.id
                   UNION ALL
                   SELECT jsonb_build_object(
                       'role', 'bundle', 'ordinal', source.ordinal,
                       'storageUri', bundle.storage_uri, 'sha256', bundle.sha256, 'bytes', bundle.bytes
                   ) AS item
                   FROM graph_version_sources source
                   JOIN artifacts bundle ON bundle.id = source.bundle_snapshot_artifact_id
                   WHERE source.graph_version_id = v.id
               ) registered
           ), '[]'::jsonb) AS source_artifacts
    FROM graph_versions v
    JOIN artifacts snapshot ON snapshot.id = v.snapshot_artifact_id
), active_graph AS (
    SELECT * FROM graph_payload WHERE active ORDER BY sequence DESC LIMIT 1
), previous_nonfixture AS (
    SELECT candidate.*
    FROM graph_payload candidate
    CROSS JOIN active_graph active
    WHERE candidate.kind = 'snapshot'
      AND candidate.published_at IS NOT NULL
      AND candidate.sequence < active.sequence
    ORDER BY candidate.sequence DESC
    LIMIT 1
)
SELECT jsonb_build_object(
    'schemaVersion', 'zoop-chat-data-inventory-1',
    'database', jsonb_build_object(
        'postgresVersion', current_setting('server_version'),
        'latestMigration', (SELECT max(version) FROM flyway_schema_history WHERE success)
    ),
    'counts', jsonb_build_object(
        'companies', (SELECT count(*) FROM companies),
        'articles', (SELECT count(*) FROM articles),
        'availableArticles', (SELECT count(*) FROM articles WHERE access_status = 'available'),
        'articleVersions', (SELECT count(*) FROM article_versions),
        'evidence', (SELECT count(*) FROM evidence),
        'verifiedEvidence', (SELECT count(*) FROM evidence WHERE quote_verified IS TRUE),
        'publishedBriefings', (SELECT count(*) FROM briefing_rounds WHERE status = 'published'),
        'nonFixtureGraphVersions', (SELECT count(*) FROM graph_versions WHERE kind = 'snapshot')
    ),
    'companyIds', COALESCE((SELECT jsonb_agg(id ORDER BY id) FROM companies), '[]'::jsonb),
    'activeGraph', (
        SELECT jsonb_build_object(
            'id', id, 'sequence', sequence, 'kind', kind, 'active', active, 'publishedAt', published_at,
            'issueCount', issue_count, 'relationCount', relation_count, 'articleCount', article_count,
            'snapshot', snapshot, 'sourceArtifacts', source_artifacts
        ) FROM active_graph
    ),
    'previousNonFixtureGraph', (
        SELECT jsonb_build_object(
            'id', id, 'sequence', sequence, 'kind', kind, 'active', active, 'publishedAt', published_at,
            'issueCount', issue_count, 'relationCount', relation_count, 'articleCount', article_count,
            'snapshot', snapshot, 'sourceArtifacts', source_artifacts
        ) FROM previous_nonfixture
    )
);
