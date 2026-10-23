package com.zoop.admin.graph;

import java.time.Instant;
import java.util.List;

/** Response shapes of the admin graph version API (A-ADM-03, FS059). */
public final class GraphVersionAdminResponse {
    private GraphVersionAdminResponse() { }

    public record GraphVersionList(String activeVersionId, List<GraphVersionOut> items,
            List<ActivationOut> activations, String nextCursor) { }

    public record GraphVersionOut(String id, long sequence, String kind, Instant createdAt, String createdBy,
            String reason, String sourceLabel, String policyVersion, long issueCount, long relationCount,
            long articleCount, Long candidateCount, String sha256, long bytes, boolean active, Instant activatedAt,
            GraphDbVersionState graphDb) { }

    public record GraphDbVersionState(String status, Long pendingJobsAtCreation, String note) { }

    public record ActivationOut(String versionId, String previousVersionId, Instant at, String adminEmail,
            String reason, String action) { }

    public record ActivateResponse(String activeVersionId, String previousActiveVersionId, boolean idempotent) { }
}
