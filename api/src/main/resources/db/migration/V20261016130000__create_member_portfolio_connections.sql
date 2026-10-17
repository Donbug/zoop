CREATE TABLE member_portfolio_connections (
    member_id text PRIMARY KEY,
    connection_id text NOT NULL UNIQUE,
    mock_portfolio_id text NOT NULL,
    connected_at timestamptz NOT NULL,
    CONSTRAINT fk_member_portfolio_connections_member FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_member_portfolio_connections_ids CHECK (
        length(connection_id) > 0 AND length(mock_portfolio_id) > 0
    )
);

CREATE TABLE member_portfolio_idempotency (
    member_id text NOT NULL,
    idempotency_key text NOT NULL,
    mock_portfolio_id text NOT NULL,
    connection_id text NOT NULL,
    connected_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_member_portfolio_idempotency PRIMARY KEY (member_id, idempotency_key),
    CONSTRAINT fk_member_portfolio_idempotency_member FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT ck_member_portfolio_idempotency_values CHECK (
        length(idempotency_key) > 0 AND length(mock_portfolio_id) > 0 AND length(connection_id) > 0
    )
);
