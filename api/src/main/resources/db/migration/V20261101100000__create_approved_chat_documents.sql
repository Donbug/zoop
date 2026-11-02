-- Approved member-facing help and screen guides for chatbot Q01. This migration
-- creates the registry only: the current drafts are deliberately not inserted.
-- A later approval migration must insert an immutable version with its approval
-- reference and effective period.
CREATE TABLE chat_document_versions (
    doc_id text NOT NULL,
    kind text NOT NULL,
    version text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    approval_ref text NOT NULL,
    approved_at timestamptz NOT NULL,
    effective_at timestamptz NOT NULL,
    retired_at timestamptz,
    CONSTRAINT pk_chat_document_versions PRIMARY KEY (doc_id, version),
    CONSTRAINT ck_chat_document_versions_kind
        CHECK (kind IN ('help', 'screen_spec')),
    CONSTRAINT ck_chat_document_versions_id_kind
        CHECK ((kind = 'help' AND doc_id LIKE 'help.%')
            OR (kind = 'screen_spec' AND doc_id LIKE 'screen.%')),
    CONSTRAINT ck_chat_document_versions_nonempty
        CHECK (length(version) BETWEEN 1 AND 80
            AND length(title) BETWEEN 1 AND 300
            AND length(body) BETWEEN 1 AND 40000
            AND length(approval_ref) BETWEEN 1 AND 500),
    CONSTRAINT ck_chat_document_versions_approved_before_effective
        CHECK (approved_at <= effective_at),
    CONSTRAINT ck_chat_document_versions_retired_after_effective
        CHECK (retired_at IS NULL OR retired_at > effective_at),
    CONSTRAINT ex_chat_document_versions_effective_period
        EXCLUDE USING gist (
            doc_id WITH =,
            tstzrange(effective_at, retired_at, '[)') WITH &&
        )
);

CREATE OR REPLACE FUNCTION guard_chat_document_version_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'approved chat document versions cannot be deleted';
    END IF;
    IF NEW.doc_id IS DISTINCT FROM OLD.doc_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.body IS DISTINCT FROM OLD.body
       OR NEW.approval_ref IS DISTINCT FROM OLD.approval_ref
       OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
       OR NEW.effective_at IS DISTINCT FROM OLD.effective_at THEN
        RAISE EXCEPTION 'approved chat document versions are immutable; insert a new version';
    END IF;
    IF NEW.retired_at IS DISTINCT FROM OLD.retired_at
       AND (OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL) THEN
        RAISE EXCEPTION 'approved chat document retirement is one-way';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_chat_document_versions_immutable
BEFORE UPDATE OR DELETE ON chat_document_versions
FOR EACH ROW EXECUTE FUNCTION guard_chat_document_version_immutability();
