package com.zoop.graph.round;

import java.time.Instant;
import java.util.Optional;

/**
 * One row of {@code graph_rounds}: a slot of the periodic public-graph round and how far the app has carried it.
 *
 * @param roundId     {@code round-yyyyMMdd'T'HHmm} in KST; the AI side's handoff id for the round is derived from it
 * @param slotAt      the slot instant
 * @param stage       current stage
 * @param startedBy   who created the row: {@code system:scheduler} or {@code admin:<id>} (manual start). Written once; a retry
 *                    is recorded as an event ({@code retried}) and an audit row, never here
 * @param attempts    attempts made at the current stage
 * @param nextAttemptAt when a waiting stage may be tried again (backoff), or empty
 * @param lease       the instance holding the row, until when, and the fencing token of that lease, or empty
 */
public record GraphRound(String roundId, Instant slotAt, GraphRoundStage stage, Optional<String> planId,
        Optional<String> planDigest, Optional<String> analysisJobId, Optional<String> handoffId,
        Optional<String> manifestDigest, Optional<String> bundleDigest, Optional<String> graphVersionId,
        Optional<String> activatedVersionId, Optional<String> activationNote, Optional<String> failureCode, int attempts,
        Optional<Instant> nextAttemptAt, Optional<Lease> lease, String startedBy, Instant createdAt, Instant updatedAt) {

    /**
     * @param token issued by {@code claim} with every new lease; every write of an outcome ({@code advance}, {@code link})
     *              carries it, so the write of a holder whose lease was taken over is refused
     */
    public record Lease(String owner, Instant until, long token) {
    }

    public boolean open() {
        return !stage.terminal();
    }
}
