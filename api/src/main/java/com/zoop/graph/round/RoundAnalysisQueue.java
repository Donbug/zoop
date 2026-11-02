package com.zoop.graph.round;

import java.util.Optional;

/**
 * The scheduler's view of the {@code analyze_plan} queue (R3 and R4): queue the admitted plan of a round under the system actor
 * and read how far its job got. Behind it is the same {@code AnalysisJobService} the admin screen uses, with the same command
 * key per plan ({@code analyze-plan:<binding>:<planId>}), so a plan is analysed once however many times a round asks.
 */
public interface RoundAnalysisQueue {

    /** @param reused true when a job for this plan existed already (queued, running or finished) and no new job was made */
    record Queued(String jobId, boolean reused) {
    }

    enum JobState {
        QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, MISSING
    }

    /** @param code the job's error code when it failed, as the admin screen shows it */
    record JobStatus(JobState state, Optional<String> code) {
    }

    /**
     * @throws com.zoop.common.exception.CustomException {@code SOURCE_UNAVAILABLE} when the worker or the service binding is not
     *         configured (the round waits), {@code REVISION_CONFLICT} or another refusal when the plan cannot be queued (the
     *         round fails with {@code plan_rejected})
     */
    Queued queue(String planId, String planDigest, String roundId, String requestId);

    JobStatus status(String jobId);
}
