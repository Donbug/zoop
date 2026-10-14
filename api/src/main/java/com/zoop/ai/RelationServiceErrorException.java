package com.zoop.ai;

import java.time.Duration;
import java.util.Optional;

import com.zoop.ai.relation.RelationJobStatus;
import com.zoop.ai.relation.RelationOperationStatus;

/**
 * The S3 relation service answered with its error envelope (schema {@code zoop-ai-internal-relation-1}). Codes are the
 * service's own lowercase ones ({@code upstream_not_allowed}, {@code source_version_conflict}, {@code source_revision_conflict},
 * {@code review_target_not_hold}, {@code review_already_pending}, {@code operation_id_unavailable}, ...). Not proof that nothing
 * happened for a mutating operation: see {@link AiServiceRejectionException}. A review refused with a 4xx recorded nothing and
 * released its operation id; a review answered with a 5xx may have been recorded, so read the operation by key before acting.
 */
public final class RelationServiceErrorException extends AiServiceRejectionException {
    private final Optional<RelationJobStatus> status;
    private final Optional<RelationOperationStatus> operationStatus;

    public RelationServiceErrorException(AiOperation operation, String requestId, int httpStatus, String code, boolean retryable,
                                         Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter,
                                         Optional<RelationJobStatus> status, Optional<RelationOperationStatus> operationStatus) {
        super(operation, requestId, httpStatus, code, retryable, runtimeCode, field, retryAfter);
        this.status = status;
        this.operationStatus = operationStatus;
    }

    /** The job status that accompanies {@code job_already_terminal}, {@code reconcile_required} and {@code job_not_recoverable}. */
    public Optional<RelationJobStatus> status() {
        return status;
    }

    /** The operation status that accompanies {@code review_not_confirmed}, {@code operation_not_recoverable}, {@code job_cancelled} and similar. */
    public Optional<RelationOperationStatus> operationStatus() {
        return operationStatus;
    }
}
