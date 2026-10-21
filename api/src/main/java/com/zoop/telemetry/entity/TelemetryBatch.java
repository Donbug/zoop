package com.zoop.telemetry.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** JPA schema mapping for Flyway-managed telemetry batch idempotency records. */
@Entity
@Table(name = "telemetry_batches")
@IdClass(TelemetryBatchId.class)
public class TelemetryBatch {
    @Id
    @Column(name = "principal_key", nullable = false, columnDefinition = "text")
    private String principalKey;

    @Id
    @Column(name = "idempotency_key", nullable = false, columnDefinition = "text")
    private String idempotencyKey;

    @JdbcTypeCode(SqlTypes.CHAR)
    @Column(name = "payload_sha256", nullable = false, length = 64, columnDefinition = "char(64)")
    private String payloadSha256;

    @Column(name = "accepted", nullable = false)
    private int accepted;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    protected TelemetryBatch() {
    }
}
