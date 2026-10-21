-- FS065 privacy-preserving interaction event source.
CREATE TABLE telemetry_batches (
    principal_key text NOT NULL,
    idempotency_key text NOT NULL,
    payload_sha256 char(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    accepted integer NOT NULL CHECK (accepted >= 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (principal_key, idempotency_key)
);

CREATE TABLE telemetry_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    principal_key text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'screen_view', 'graph_node_select', 'graph_edge_select',
        'briefing_view', 'briefing_issue_open', 'ai_question'
    )),
    screen text CHECK (screen IS NULL OR screen IN ('main', 'briefing', 'ai')),
    target_id text,
    round_id text,
    view_id text NOT NULL CHECK (view_id ~ '^[A-Za-z0-9-]{8,40}$'),
    occurred_at timestamptz NOT NULL,
    CONSTRAINT ck_telemetry_round_id_identifier CHECK (
        round_id IS NULL OR round_id ~ '^[A-Za-z0-9._:/-]{1,256}$'
    ),
    CONSTRAINT ck_telemetry_event_shape CHECK (
        (event_type = 'screen_view' AND screen IS NOT NULL AND target_id IS NULL AND round_id IS NULL)
        OR (event_type IN ('graph_node_select', 'graph_edge_select') AND screen IS NULL
            AND target_id IS NOT NULL AND round_id IS NULL)
        OR (event_type = 'briefing_view' AND screen IS NULL AND target_id IS NOT NULL AND round_id IS NULL)
        OR (event_type = 'briefing_issue_open' AND screen IS NULL AND target_id IS NOT NULL AND round_id IS NOT NULL)
        OR (event_type = 'ai_question' AND screen IS NULL AND round_id IS NULL)
    )
);

CREATE INDEX ix_telemetry_events_time_type ON telemetry_events (occurred_at, event_type);
CREATE INDEX ix_telemetry_events_target_time ON telemetry_events (target_id, occurred_at)
    WHERE target_id IS NOT NULL;
CREATE INDEX ix_telemetry_events_principal_view ON telemetry_events
    (principal_key, event_type, view_id, occurred_at);
CREATE INDEX ix_telemetry_batches_created ON telemetry_batches (created_at);
