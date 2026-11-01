-- Exact first POST bodies commit before transport. Recovery reads scoped status before retransmitting these bytes.
CREATE TABLE graph_round_requests (
    round_id text NOT NULL REFERENCES graph_rounds (round_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('run', 'freeze')),
    body bytea NOT NULL CHECK (octet_length(body) BETWEEN 1 AND 4001024),
    body_sha256 text NOT NULL CHECK (body_sha256 ~ '^[a-f0-9]{64}$'),
    service_binding text NOT NULL CHECK (service_binding ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (round_id, kind)
);
CREATE TRIGGER tr_graph_round_requests_guard BEFORE UPDATE OR DELETE ON graph_round_requests
    FOR EACH ROW EXECUTE FUNCTION graph_round_events_guard();
