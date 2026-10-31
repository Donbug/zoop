package com.zoop.admin.pipeline;

import java.util.List;

import tools.jackson.databind.JsonNode;

/** OpenAPI {@code GraphRoundList}, {@code GraphRoundDetail}, {@code GraphRoundOut}, {@code GraphRoundEventOut} and the overview's {@code rounds}. */
public final class GraphRoundAdminResponse {
    private GraphRoundAdminResponse() {
    }

    public record GraphRoundList(List<GraphRoundOut> items, String nextCursor) {
    }

    public record GraphRoundDetail(GraphRoundOut round, List<GraphRoundEventOut> events) {
    }

    /**
     * One round as the admin sees it. Codes, ids and digests only: no path, body or secret is ever on a round row.
     *
     * @param stage         {@code scheduled} … {@code imported} | {@code skipped} | {@code failed}
     * @param startedBy     who created the row: {@code system:scheduler} or {@code admin:<id>} (manual start); a retry is an event
     * @param failureCode   only while {@code failed}
     * @param activatedVersionId the version the auto-activation (or an admin) made public for this round, recorded afterwards
     */
    public record GraphRoundOut(String roundId, String slotAt, String stage, String startedBy, int attempts, String nextAttemptAt,
            GraphRoundPlan plan, String analysisJobId, GraphRoundHandoff handoff, String graphVersionId, String activatedVersionId,
            String activationNote, String failureCode, GraphRoundLease lease, String createdAt, String updatedAt) {
    }

    public record GraphRoundPlan(String planId, String planDigest) {
    }

    public record GraphRoundHandoff(String handoffId, String manifestDigest, String bundleDigest) {
    }

    public record GraphRoundLease(String owner, String until) {
    }

    public record GraphRoundEventOut(long id, String at, String stage, String outcome, String code, String requestId,
            JsonNode detail) {
    }

    /**
     * The overview's {@code rounds} section: the scheduler's state and the most recent rounds.
     *
     * @param enabled    whether the round scheduler runs in this application
     * @param nextSlotAt the next slot it will open (null when disabled)
     * @param lastTickAt when it last ran (null when disabled or not yet)
     * @param openRounds rounds not yet terminal
     */
    public record GraphRoundsSection(boolean enabled, String nextSlotAt, String lastTickAt, long openRounds, List<GraphRoundOut> recent) {
    }
}
