package com.zoop.ai.entity;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * ERD v6 section 32. One row per AI attempt. A row written from an AI call receipt (it has a {@code receipt_artifact_id}) is
 * immutable (enforced by a DB trigger). The operator analysis writes it through JDBC; this mapping exists so that
 * {@code ddl-auto: validate} checks the Flyway schema.
 */
@Entity
@Table(name = "ai_executions")
public class AiExecution {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "feature", nullable = false, columnDefinition = "text")
    private String feature;

    @Column(name = "execution_mode", nullable = false, columnDefinition = "text")
    private String executionMode;

    @Column(name = "status", nullable = false, columnDefinition = "text")
    private String status;

    @Column(name = "chat_job_id", columnDefinition = "text")
    private String chatJobId;

    @Column(name = "briefing_attempt_id", columnDefinition = "text")
    private String briefingAttemptId;

    @Column(name = "analysis_job_id", columnDefinition = "text")
    private String analysisJobId;

    @Column(name = "document_analysis_id", columnDefinition = "text")
    private String documentAnalysisId;

    @Column(name = "ai_job_id", columnDefinition = "text")
    private String aiJobId;

    @Column(name = "ai_attempt_id", columnDefinition = "text")
    private String aiAttemptId;

    @Column(name = "stage", columnDefinition = "text")
    private String stage;

    @Column(name = "receipt_artifact_id", columnDefinition = "text")
    private String receiptArtifactId;

    @Column(name = "grant_id", columnDefinition = "text")
    private String grantId;

    @Column(name = "grant_revision", columnDefinition = "text")
    private String grantRevision;

    @Column(name = "grant_checked_at", columnDefinition = "timestamptz")
    private Instant grantCheckedAt;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "grant_scope", columnDefinition = "jsonb")
    private Map<String, Object> grantScope;

    @Column(name = "attempt_no", columnDefinition = "integer")
    private Integer attemptNo;

    @Column(name = "provider", columnDefinition = "text")
    private String provider;

    @Column(name = "model", columnDefinition = "text")
    private String model;

    @Column(name = "prompt_version", columnDefinition = "text")
    private String promptVersion;

    @Column(name = "reasoning_effort", columnDefinition = "text")
    private String reasoningEffort;

    @Column(name = "input_tokens", columnDefinition = "bigint")
    private Long inputTokens;

    @Column(name = "output_tokens", columnDefinition = "bigint")
    private Long outputTokens;

    @Column(name = "reasoning_tokens", columnDefinition = "bigint")
    private Long reasoningTokens;

    @Column(name = "estimated_cost", columnDefinition = "numeric")
    private BigDecimal estimatedCost;

    @Column(name = "actual_cost", columnDefinition = "numeric")
    private BigDecimal actualCost;

    @Column(name = "currency", columnDefinition = "text")
    private String currency;

    @Column(name = "error_code", columnDefinition = "text")
    private String errorCode;

    @Column(name = "error_message", columnDefinition = "text")
    private String errorMessage;

    @Column(name = "started_at", nullable = false, columnDefinition = "timestamptz")
    private Instant startedAt;

    @Column(name = "finished_at", columnDefinition = "timestamptz")
    private Instant finishedAt;

    protected AiExecution() {
    }
}
