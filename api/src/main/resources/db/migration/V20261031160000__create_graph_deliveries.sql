-- Immutable producer outbox and explicit serving-root acknowledgements.
CREATE TABLE graph_delivery_packages (
    version_id text NOT NULL REFERENCES graph_versions(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    destination_id text NOT NULL CHECK (destination_id ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    handoff_id text NOT NULL CHECK (length(handoff_id) BETWEEN 1 AND 200),
    manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
    bundle_digest text NOT NULL CHECK (bundle_digest ~ '^[0-9a-f]{64}$'),
    manifest text NOT NULL CHECK (octet_length(manifest) BETWEEN 1 AND 16777216),
    package_digest text NOT NULL CHECK (package_digest ~ '^[0-9a-f]{64}$'),
    file_count integer NOT NULL CHECK (file_count >= 2),
    total_bytes bigint NOT NULL CHECK (total_bytes >= 0),
    sealed_by text NOT NULL CHECK (sealed_by ~ '^[A-Za-z0-9._@-]{1,100}$'),
    sealed_at timestamptz NOT NULL,
    PRIMARY KEY (version_id, destination_id),
    UNIQUE (version_id, destination_id, package_digest)
);
CREATE TABLE graph_delivery_contents (
    artifact_id text PRIMARY KEY REFERENCES artifacts(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    bytes bigint NOT NULL CHECK (bytes BETWEEN 0 AND 16777216),
    content bytea NOT NULL,
    stored_at timestamptz NOT NULL,
    CHECK (octet_length(content) = bytes)
);
CREATE TABLE graph_delivery_destinations (
    destination_id text PRIMARY KEY CHECK (destination_id ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    marker_sha256 text NOT NULL CHECK (marker_sha256 ~ '^[0-9a-f]{64}$'),
    marker_bytes bigint NOT NULL CHECK (marker_bytes BETWEEN 1 AND 16777216),
    registered_at timestamptz NOT NULL
);
CREATE TABLE graph_delivery_installs (
    version_id text NOT NULL,
    destination_id text NOT NULL REFERENCES graph_delivery_destinations(destination_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    package_digest text NOT NULL CHECK (package_digest ~ '^[0-9a-f]{64}$'),
    installed_at timestamptz NOT NULL,
    PRIMARY KEY (version_id, destination_id),
    FOREIGN KEY (version_id, destination_id, package_digest)
        REFERENCES graph_delivery_packages(version_id, destination_id, package_digest) ON UPDATE RESTRICT ON DELETE RESTRICT
);
CREATE INDEX ix_graph_delivery_packages_destination ON graph_delivery_packages(destination_id);
CREATE FUNCTION graph_delivery_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'graph delivery records are insert-only' USING ERRCODE = 'restrict_violation';
END
$$;
CREATE TRIGGER tr_graph_delivery_packages_guard BEFORE UPDATE OR DELETE ON graph_delivery_packages
    FOR EACH ROW EXECUTE FUNCTION graph_delivery_immutable_guard();
CREATE TRIGGER tr_graph_delivery_contents_guard BEFORE UPDATE OR DELETE ON graph_delivery_contents
    FOR EACH ROW EXECUTE FUNCTION graph_delivery_immutable_guard();
CREATE TRIGGER tr_graph_delivery_destinations_guard BEFORE UPDATE OR DELETE ON graph_delivery_destinations
    FOR EACH ROW EXECUTE FUNCTION graph_delivery_immutable_guard();
CREATE TRIGGER tr_graph_delivery_installs_guard BEFORE UPDATE OR DELETE ON graph_delivery_installs
    FOR EACH ROW EXECUTE FUNCTION graph_delivery_immutable_guard();
