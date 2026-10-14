-- ERD v6 section 14-16: artifact registry, document identity and immutable document versions (FS056 document side).
-- This migration is the first writer of the shared `artifacts` table; other features reference it and must not redefine it.
-- `evidence`, `document_analyses` and `analysis_jobs` depend on companies/analysis storage and are not part of it.

CREATE TABLE artifacts (
    id text PRIMARY KEY,
    kind text NOT NULL,
    storage_uri text NOT NULL,
    sha256 text NOT NULL,
    bytes bigint NOT NULL,
    media_type text NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT uq_artifacts_storage_uri UNIQUE (storage_uri),
    CONSTRAINT ck_artifacts_kind CHECK (kind IN (
        'raw_document', 'extracted_text', 'summary_text', 'analysis_result', 'exact_receipt', 'semantic_receipt',
        'verification_receipt', 'ai_submit', 'ai_call_receipt', 'graph_snapshot', 'briefing_input', 'chat_recovery')),
    CONSTRAINT ck_artifacts_bytes CHECK (bytes >= 0),
    CONSTRAINT ck_artifacts_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE articles (
    id text PRIMARY KEY,
    kind text NOT NULL,
    provider text NOT NULL,
    provider_key text,
    lineage_key text,
    current_version text,
    access_status text NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT ck_articles_kind CHECK (kind IN ('news', 'disclosure')),
    CONSTRAINT ck_articles_access_status CHECK (access_status IN ('available', 'private', 'deleted'))
);

CREATE UNIQUE INDEX ux_articles_provider_key ON articles (provider, provider_key) WHERE provider_key IS NOT NULL;

CREATE TABLE article_versions (
    article_id text NOT NULL,
    version text NOT NULL,
    title text,
    publisher text,
    url text,
    published_at timestamptz,
    published_date date,
    publication_precision text NOT NULL,
    raw_artifact_id text,
    text_artifact_id text NOT NULL,
    collected_at timestamptz NOT NULL,
    CONSTRAINT pk_article_versions PRIMARY KEY (article_id, version),
    CONSTRAINT fk_article_versions_article FOREIGN KEY (article_id) REFERENCES articles (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_article_versions_raw_artifact FOREIGN KEY (raw_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_article_versions_text_artifact FOREIGN KEY (text_artifact_id) REFERENCES artifacts (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_article_versions_publication CHECK (
        (publication_precision = 'datetime' AND published_at IS NOT NULL AND published_date IS NULL)
        OR (publication_precision = 'day' AND published_at IS NULL AND published_date IS NOT NULL)
        OR (publication_precision = 'unknown' AND published_at IS NULL AND published_date IS NULL))
);

CREATE INDEX ix_article_versions_collected ON article_versions (article_id, collected_at DESC);
CREATE INDEX ix_article_versions_published_at ON article_versions (published_at);

-- The pointer is NULL until an explicit compare-and-set; a NULL component disables the FK check (MATCH SIMPLE).
ALTER TABLE articles ADD CONSTRAINT fk_articles_current_version
    FOREIGN KEY (id, current_version) REFERENCES article_versions (article_id, version)
    ON UPDATE RESTRICT ON DELETE RESTRICT;

-- ERD v6: artifacts and article versions are immutable (no URI overwrite); of an article only access_status and
-- current_version may change. DELETE is deliberately not blocked here: retention and deletion policy is a separate decision.
CREATE FUNCTION document_registry_reject_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_artifacts_immutable BEFORE UPDATE ON artifacts
    FOR EACH ROW EXECUTE FUNCTION document_registry_reject_update();

CREATE TRIGGER tr_article_versions_immutable BEFORE UPDATE ON article_versions
    FOR EACH ROW EXECUTE FUNCTION document_registry_reject_update();

CREATE FUNCTION document_registry_reject_article_identity_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.kind, NEW.provider, NEW.provider_key, NEW.lineage_key, NEW.created_at)
        IS DISTINCT FROM (OLD.id, OLD.kind, OLD.provider, OLD.provider_key, OLD.lineage_key, OLD.created_at) THEN
        RAISE EXCEPTION 'article identity is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_articles_identity_immutable BEFORE UPDATE ON articles
    FOR EACH ROW EXECUTE FUNCTION document_registry_reject_article_identity_update();
