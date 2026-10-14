package com.zoop.document.entity;

import java.time.Instant;
import java.util.Map;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * ERD v6 section 18. One row per requested document analysis stage. The operator analysis writes it through JDBC; this
 * mapping exists so that {@code ddl-auto: validate} checks the Flyway schema. A finished row is immutable apart from
 * {@code revoked_at} and {@code updated_at} (enforced by a DB trigger).
 */
@Entity
@Table(name = "document_analyses")
public class DocumentAnalysis {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "article_id", nullable = false, columnDefinition = "text")
    private String articleId;

    @Column(name = "article_version", nullable = false, columnDefinition = "text")
    private String articleVersion;

    @Column(name = "stage", nullable = false, columnDefinition = "text")
    private String stage;

    @Column(name = "company_id", columnDefinition = "text")
    private String companyId;

    @Column(name = "request_no", nullable = false, columnDefinition = "bigint")
    private long requestNo;

    @Column(name = "status", nullable = false, columnDefinition = "text")
    private String status;

    @Column(name = "reason", columnDefinition = "text")
    private String reason;

    @Column(name = "result_version", columnDefinition = "text")
    private String resultVersion;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "result", columnDefinition = "jsonb")
    private Map<String, Object> result;

    @Column(name = "summary_text_artifact_id", columnDefinition = "text")
    private String summaryTextArtifactId;

    @Column(name = "result_artifact_id", columnDefinition = "text")
    private String resultArtifactId;

    @Column(name = "exact_receipt_id", columnDefinition = "text")
    private String exactReceiptId;

    @Column(name = "semantic_receipt_id", columnDefinition = "text")
    private String semanticReceiptId;

    @Column(name = "grant_reference", columnDefinition = "text")
    private String grantReference;

    @Column(name = "grant_revision", columnDefinition = "text")
    private String grantRevision;

    @Column(name = "grant_checked_at", columnDefinition = "timestamptz")
    private Instant grantCheckedAt;

    @Column(name = "revoked_at", columnDefinition = "timestamptz")
    private Instant revokedAt;

    @Column(name = "model", columnDefinition = "text")
    private String model;

    @Column(name = "prompt_version", columnDefinition = "text")
    private String promptVersion;

    @Column(name = "reasoning_effort", columnDefinition = "text")
    private String reasoningEffort;

    @Column(name = "analysis_job_id", columnDefinition = "text")
    private String analysisJobId;

    @Column(name = "ai_job_id", columnDefinition = "text")
    private String aiJobId;

    @Column(name = "owner_token", columnDefinition = "text")
    private String ownerToken;

    @Column(name = "lease_until", columnDefinition = "timestamptz")
    private Instant leaseUntil;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "produced_at", columnDefinition = "timestamptz")
    private Instant producedAt;

    @Column(name = "updated_at", nullable = false, columnDefinition = "timestamptz")
    private Instant updatedAt;

    protected DocumentAnalysis() {
    }
}
