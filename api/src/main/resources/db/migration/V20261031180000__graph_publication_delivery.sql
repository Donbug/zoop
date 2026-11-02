ALTER TABLE graph_delivery_packages
    ALTER COLUMN handoff_id DROP NOT NULL,
    ALTER COLUMN manifest_digest DROP NOT NULL,
    ALTER COLUMN bundle_digest DROP NOT NULL,
    ADD COLUMN publication_id text,
    ADD COLUMN publication_receipt_sha256 text,
    ADD CONSTRAINT ck_graph_delivery_package_identity CHECK (
        (handoff_id IS NOT NULL AND manifest_digest IS NOT NULL AND bundle_digest IS NOT NULL
            AND publication_id IS NULL AND publication_receipt_sha256 IS NULL)
        OR
        (handoff_id IS NULL AND manifest_digest IS NULL AND bundle_digest IS NULL
            AND publication_id IS NOT NULL AND publication_id ~ '^publication:[0-9a-f]{64}$'
            AND publication_receipt_sha256 IS NOT NULL AND publication_receipt_sha256 ~ '^[0-9a-f]{64}$')
    );
