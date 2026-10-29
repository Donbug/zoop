package com.zoop.graph.round;

import java.time.Instant;
import java.util.Objects;

/**
 * What one attempt changes on a round row, applied together with the event that records the attempt. A {@code null} field is
 * left as it is; {@code failureCode} is required when the stage becomes {@link GraphRoundStage#FAILED} and cleared otherwise.
 *
 * @param countAttempt  one more attempt at the (new) stage
 * @param resetAttempts the stage changed: attempts start again at 0 (or 1 with {@code countAttempt})
 */
public record GraphRoundPatch(GraphRoundStage stage, String planId, String planDigest, String analysisJobId, String handoffId,
        String manifestDigest, String bundleDigest, String graphVersionId, String failureCode, Instant nextAttemptAt,
        boolean clearNextAttempt, boolean countAttempt, boolean resetAttempts) {

    public GraphRoundPatch {
        Objects.requireNonNull(stage, "stage");
        if ((stage == GraphRoundStage.FAILED) != (failureCode != null)) {
            throw new IllegalArgumentException("failureCode is required exactly when the stage is failed");
        }
    }

    /** The row moves to {@code stage}; attempts start again. */
    public static GraphRoundPatch advanceTo(GraphRoundStage stage) {
        return new GraphRoundPatch(stage, null, null, null, null, null, null, null, null, null, true, false, true);
    }

    /** The row stays at {@code stage} and one more attempt is counted; the next attempt is at {@code nextAttemptAt}. */
    public static GraphRoundPatch waitAt(GraphRoundStage stage, Instant nextAttemptAt) {
        return new GraphRoundPatch(stage, null, null, null, null, null, null, null, null, nextAttemptAt, false, true, false);
    }

    /** The row fails with {@code failureCode}; the failing attempt is counted and the count is kept for the admin view. */
    public static GraphRoundPatch fail(String failureCode) {
        return new GraphRoundPatch(GraphRoundStage.FAILED, null, null, null, null, null, null, null, failureCode, null, true,
                true, false);
    }

    public GraphRoundPatch plan(String planId, String planDigest) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts);
    }

    public GraphRoundPatch analysisJob(String analysisJobId) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts);
    }

    public GraphRoundPatch handoff(String handoffId, String manifestDigest, String bundleDigest) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts);
    }

    public GraphRoundPatch graphVersion(String graphVersionId) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts);
    }
}
