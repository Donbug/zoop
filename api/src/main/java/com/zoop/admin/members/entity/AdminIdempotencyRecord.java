package com.zoop.admin.members.entity;

import java.time.Instant;
import java.util.Map;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** JPA schema mapping for Flyway-managed idempotency records (writes remain in JDBC repository). */
@Entity
@Table(name = "idempotency_records")
public class AdminIdempotencyRecord {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "principal_kind", nullable = false, columnDefinition = "text")
    private String principalKind;

    @Column(name = "principal_id", nullable = false, columnDefinition = "text")
    private String principalId;

    @Column(name = "method", nullable = false, columnDefinition = "text")
    private String method;

    @Column(name = "path", nullable = false, columnDefinition = "text")
    private String path;

    @Column(name = "idem_key", nullable = false, columnDefinition = "text")
    private String idemKey;

    @JdbcTypeCode(SqlTypes.CHAR)
    @Column(name = "request_hash", nullable = false, length = 64, columnDefinition = "char(64)")
    private String requestHash;

    @Column(name = "status", nullable = false, columnDefinition = "text")
    private String status;

    @Column(name = "resource_type", columnDefinition = "text")
    private String resourceType;

    @Column(name = "resource_id", columnDefinition = "text")
    private String resourceId;

    @Column(name = "owner_token", columnDefinition = "text")
    private String ownerToken;

    @Column(name = "lease_until", columnDefinition = "timestamptz")
    private Instant leaseUntil;

    private Integer responseStatus;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "response_body", columnDefinition = "jsonb")
    private Map<String, Object> responseBody;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "expires_at", columnDefinition = "timestamptz")
    private Instant expiresAt;

    protected AdminIdempotencyRecord() {
    }
}
