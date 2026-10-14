package com.zoop.document.analysis.repository;

import java.time.Instant;

/**
 * The columns of {@code document_analyses} the operator analysis reads. {@code result} (the stored DTO) is written but never
 * read back here; {@code analysis_job_id}, {@code owner_token}, {@code lease_until}, {@code revoked_at} and
 * {@code summary_text_artifact_id} belong to other owners or later work and are always NULL for the rows this writes.
 */
public record AnalysisRow(String id, String articleId, String articleVersion, String stage, String companyId, long requestNo,
        String status, String reason, String resultVersion, String resultArtifactId, String exactReceiptId,
        String semanticReceiptId, String grantReference, String grantRevision, Instant grantCheckedAt, String model,
        String promptVersion, String reasoningEffort, String aiJobId, Instant createdAt, Instant producedAt, Instant updatedAt) {
}
