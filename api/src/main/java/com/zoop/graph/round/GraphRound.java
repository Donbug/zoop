package com.zoop.graph.round;

import java.time.Instant;
import java.util.Optional;

/**
 * One row of {@code graph_rounds}: a slot of the periodic public-graph round and how far the app has carried it.
 *
 * @param roundId     {@code round-yyyyMMdd'T'HHmm} in KST; the AI side's handoff id for the round is derived from it
 * @param slotAt      the slot instant
 * @param stage       current stage
 * @param startedBy   {@code system:scheduler} or {@code admin:<id>} (manual start or retry)
 * @param attempts    attempts made at the current stage
 * @param nextAttemptAt when a waiting stage may be tried again (backoff), or empty
 * @param lease       the instance holding the row and until when, or empty
 */
public record GraphRound(String roundId, Instant slotAt, GraphRoundStage stage, Optional<String> planId,
        Optional<String> planDigest, Optional<String> analysisJobId, Optional<String> handoffId,
        Optional<String> manifestDigest, Optional<String> bundleDigest, Optional<String> graphVersionId,
        Optional<String> activatedVersionId, Optional<String> activationNote, Optional<String> failureCode, int attempts,
        Optional<Instant> nextAttemptAt, Optional<Lease> lease, String startedBy, Instant createdAt, Instant updatedAt) {

    public record Lease(String owner, Instant until) {
    }

    public boolean open() {
        return !stage.terminal();
    }
}
