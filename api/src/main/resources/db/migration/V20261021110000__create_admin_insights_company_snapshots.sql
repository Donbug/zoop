CREATE TABLE admin_insights_company_snapshots (
    id text PRIMARY KEY,
    window_name text NOT NULL CHECK (window_name IN ('7d', '30d', 'all')),
    page_size integer NOT NULL CHECK (page_size BETWEEN 1 AND 100),
    as_of timestamptz NOT NULL,
    total_companies bigint NOT NULL CHECK (total_companies >= 0),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE INDEX ix_admin_insights_company_snapshots_expiry
    ON admin_insights_company_snapshots (expires_at);

CREATE TABLE admin_insights_company_snapshot_rows (
    snapshot_id text NOT NULL REFERENCES admin_insights_company_snapshots(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    company_id text NOT NULL,
    name text NOT NULL,
    ticker text,
    watchlist_members bigint NOT NULL CHECK (watchlist_members >= 0),
    holding_members bigint NOT NULL CHECK (holding_members >= 0),
    node_views bigint NOT NULL CHECK (node_views >= 0),
    ai_questions bigint NOT NULL CHECK (ai_questions >= 0),
    PRIMARY KEY (snapshot_id, ordinal),
    UNIQUE (snapshot_id, company_id)
);
