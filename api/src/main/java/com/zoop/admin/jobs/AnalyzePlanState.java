package com.zoop.admin.jobs;

import com.zoop.ai.ExecutionMode;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionJobStatus;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.plan.PlanReference;
import com.zoop.ai.relation.RelationJobStatus;
import com.zoop.ai.relation.RelationSubmission;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Durable, content-free orchestration vocabulary. A processing handoff is not publication or read authority. */
public final class AnalyzePlanState {
    private AnalyzePlanState() {}

    public record ServiceBinding(String digest, String expectedPrincipal) {
        public ServiceBinding {
            PipelineJob.requireDigest("serviceBinding", digest);
            if (expectedPrincipal == null || !com.zoop.ai.plan.PlanIdentity.PRINCIPAL.matcher(expectedPrincipal).matches()) {
                throw new IllegalArgumentException("invalid principal");
            }
        }
        public static ServiceBinding of(String canonicalBaseUrl, String principal) {
            var node = StrictJson.newObject();
            node.put("format", "zoop-app-analyze-plan-binding-1");
            node.put("baseUrl", canonicalBaseUrl);
            node.put("principal", principal);
            return new ServiceBinding(Canonical.digest(node), principal);
        }
    }

    public record PlanRegistration(PlanReference reference, ServiceBinding binding, Instant registeredAt,
            String registeredBy, Instant admissionIntentAt, String admissionId, Instant acceptedAt,
            Long policyRevision, String policyDigest, String receiptSha256, String manifestDigest,
            String authorityState, String authorityReason, boolean cancelRequested) {}

    public record AnalyzePlanClaim(String appJobId, String planId, String ownerToken, int attemptNo,
            Instant deadline, Instant leaseUntil) {}
    public enum StageKind { S2, S3 }
    public enum StageAction { SUBMIT, RECOVER, CANCEL }

    public record StageCheckpoint(String schemaVersion, String state, Instant intentAt, Instant acceptedObservedAt,
            StageStatus lastStatus, Instant resultObservedAt, String resultContentSha256,
            List<PipelineJob.Receipt> receipts, String failureCategory, String failureCode,
            int consecutiveFailures, int recoveryDispatches) {
        public static StageCheckpoint initial() {
            return new StageCheckpoint("zoop-app-analyze-plan-stage-1", "unsubmitted", null, null, null,
                    null, null, null, null, null, 0, 0);
        }
    }

    /** Exactly one typed status branch; includes all runtime usage/dispatch/identity fields, never source text. */
    public record StageStatus(ExtractionJobStatus extraction, RelationJobStatus relation) {
        public StageStatus {
            if ((extraction == null) == (relation == null)) throw new IllegalArgumentException("one status required");
        }
    }

    /** {@code s2ResultSha256} is the S2 result content hash the unit's S2 checkpoint recorded (null until observed). */
    public record StageWork(String planId, int ordinal, StageKind stage, ExtractionSubmission extractionSubmit,
            RelationSubmission relationSubmit, String extractionInputDigest, String s3InputDigest,
            StageCheckpoint checkpoint, String s2ResultSha256) {
        public String jobId() { return stage == StageKind.S2 ? extractionSubmit.jobId() : relationSubmit.jobId(); }
    }

    public record StageObservation(StageStatus status, String resultContentSha256, List<PipelineJob.Receipt> receipts,
            String failureCategory, String failureCode) {
        public StageObservation {
            if (resultContentSha256 != null) {
                PipelineJob.requireDigest("resultContentSha256", resultContentSha256);
                Objects.requireNonNull(status, "result status");
                receipts = List.copyOf(Objects.requireNonNull(receipts, "result receipts"));
            }
        }
        public static StageObservation status(ExtractionJobStatus value) {
            return new StageObservation(new StageStatus(value, null), null, null, null, null);
        }
        public static StageObservation status(RelationJobStatus value) {
            return new StageObservation(new StageStatus(null, value), null, null, null, null);
        }
        public static StageObservation failure(String category, String code) {
            return new StageObservation(null, null, null, category, code);
        }
    }

    public record AnalyzePlanTerminal(String status, String failureCategory, String errorCode) {
        public AnalyzePlanTerminal {
            if (!List.of("succeeded", "failed", "cancelled").contains(status)) throw new IllegalArgumentException("terminal status");
        }
    }
    public record ReadyUnitReference(String planId, String planDigest, String admissionId, String manifestDigest,
            int ordinal, String unitKey, String extractionJobId, String extractionInputDigest,
            String relationJobId, String relationInputDigest, PipelineJob.SourceKind sourceKind, ExecutionMode executionMode,
            Instant s2ResultObservedAt, Instant s3ResultObservedAt,
            String s2ResultContentSha256, String s3ResultContentSha256) {}
}
