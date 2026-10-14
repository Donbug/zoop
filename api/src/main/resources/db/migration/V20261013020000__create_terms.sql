CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE terms (
    id text PRIMARY KEY,
    title text NOT NULL,
    required boolean NOT NULL,
    created_at timestamptz NOT NULL,
    retired_at timestamptz,
    CONSTRAINT ck_terms_retired_after_created
        CHECK (retired_at IS NULL OR retired_at > created_at)
);

CREATE TABLE term_versions (
    term_id text NOT NULL,
    version text NOT NULL,
    title_snapshot text NOT NULL,
    required_snapshot boolean NOT NULL,
    body text NOT NULL,
    approved_at timestamptz NOT NULL,
    effective_at timestamptz NOT NULL,
    retired_at timestamptz,
    CONSTRAINT pk_term_versions PRIMARY KEY (term_id, version),
    CONSTRAINT fk_term_versions_term
        FOREIGN KEY (term_id) REFERENCES terms (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT ck_term_versions_approved_before_effective
        CHECK (approved_at <= effective_at),
    CONSTRAINT ck_term_versions_retired_after_effective
        CHECK (retired_at IS NULL OR retired_at > effective_at),
    CONSTRAINT ex_term_versions_effective_period
        EXCLUDE USING gist (
            term_id WITH =,
            tstzrange(effective_at, retired_at, '[)') WITH &&
        )
);

CREATE TABLE term_agreements (
    member_id text NOT NULL,
    term_id text NOT NULL,
    term_version text NOT NULL,
    accepted boolean NOT NULL,
    accepted_at timestamptz NOT NULL,
    CONSTRAINT pk_term_agreements
        PRIMARY KEY (member_id, term_id, term_version),
    CONSTRAINT fk_term_agreements_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_term_agreements_version
        FOREIGN KEY (term_id, term_version)
        REFERENCES term_versions (term_id, version)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX ix_term_agreements_version
    ON term_agreements (term_id, term_version);
