package com.zoop.graph.round;

import java.time.Instant;
import java.util.Objects;

/**
 * What one attempt changes on a round row, applied together with the event that records the attempt. A {@code null} field is
 * left as it is; {@code failureCode} is required when the stage becomes {@link GraphRoundStage#FAILED} and cleared otherwise.
 *
 * @param countAttempt  one more attempt at the (new) stage
 * @param resetAttempts the stage changed: attempts start again at 0 (or 1 with {@code countAttempt})
 * @param clearGraphVersion a retry: the version the round linked is forgotten (the version row stays; the retried import links
 *                      its own). The only way the column goes from one value to another, since the row guard refuses a change
 *                      between two values
 */
public record GraphRoundPatch(GraphRoundStage stage, String planId, String planDigest, String analysisJobId, String handoffId,
        String manifestDigest, String bundleDigest, String graphVersionId, String failureCode, Instant nextAttemptAt,
        boolean clearNextAttempt, boolean countAttempt, boolean resetAttempts, boolean clearGraphVersion) {

    public GraphRoundPatch {
        Objects.requireNonNull(stage, "stage");
        if ((stage == GraphRoundStage.FAILED) != (failureCode != null)) {
            throw new IllegalArgumentException("failureCode is required exactly when the stage is failed");
        }
        if (clearGraphVersion && (graphVersionId != null || stage.terminal())) {
            throw new IllegalArgumentException("a retry clears the version and resumes at an open stage");
        }
    }

    /** The row moves to {@code stage}; attempts start again. */
    public static GraphRoundPatch advanceTo(GraphRoundStage stage) {
        return new GraphRoundPatch(stage, null, null, null, null, null, null, null, null, null, true, false, true, false);
    }

    /** A retry: the row resumes at the open {@code stage}, attempts start again, and the version it had linked is forgotten. */
    public static GraphRoundPatch retryAt(GraphRoundStage stage) {
        return new GraphRoundPatch(stage, null, null, null, null, null, null, null, null, null, true, false, true, true);
    }

    /** The row stays at {@code stage} and one more attempt is counted; the next attempt is at {@code nextAttemptAt}. */
    public static GraphRoundPatch waitAt(GraphRoundStage stage, Instant nextAttemptAt) {
        return new GraphRoundPatch(stage, null, null, null, null, null, null, null, null, nextAttemptAt, false, true, false,
                false);
    }

    /** The row fails with {@code failureCode}; the failing attempt is counted and the count is kept for the admin view. */
    public static GraphRoundPatch fail(String failureCode) {
        return new GraphRoundPatch(GraphRoundStage.FAILED, null, null, null, null, null, null, null, failureCode, null, true,
                true, false, false);
    }

    public GraphRoundPatch plan(String planId, String planDigest) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts, clearGraphVersion);
    }

    public GraphRoundPatch analysisJob(String analysisJobId) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts, clearGraphVersion);
    }

    public GraphRoundPatch handoff(String handoffId, String manifestDigest, String bundleDigest) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts, clearGraphVersion);
    }

    public GraphRoundPatch graphVersion(String graphVersionId) {
        return new GraphRoundPatch(stage, planId, planDigest, analysisJobId, handoffId, manifestDigest, bundleDigest,
                graphVersionId, failureCode, nextAttemptAt, clearNextAttempt, countAttempt, resetAttempts, clearGraphVersion);
    }
}
