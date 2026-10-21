package com.zoop.ai;

import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * The vocabulary the S2 extraction and S3 relation job families share on the wire: the same job states, resume modes, next
 * actions, dispatch rows, delivery gate and content-free receipts. Each family's own status record composes these with its own
 * identity fields. Every enum constant's wire value is its lower-case name ({@code IN_FLIGHT} is {@code in_flight}).
 *
 * <p>A job state is the runtime's: {@code READY} is a ready candidate set, never an approval, a publication or the public
 * {@code completed}.
 */
public final class PipelineJob {
    /** A SHA-256 digest as the service writes it. */
    public static final Pattern DIGEST = Pattern.compile("[0-9a-f]{64}");

    private PipelineJob() {
    }

    /** Same rule as the S1 job id: {@code [A-Za-z0-9_.-]{1,120}} without the path segments {@code .} and {@code ..}. */
    public static String requireId(String name, String value) {
        if (value == null || !AnalysisSubmission.JOB_ID.matcher(value).matches()) {
            throw new IllegalArgumentException(name + " must match " + AnalysisSubmission.JOB_ID.pattern());
        }
        return value;
    }

    public static String requireDigest(String name, String value) {
        if (value == null || !DIGEST.matcher(value).matches()) {
            throw new IllegalArgumentException(name + " must be a lower-case SHA-256 hex digest");
        }
        return value;
    }

    public enum State {
        QUEUED, RUNNING, RECONCILING, STOPPED, READY, CANCELLED
    }

    public enum ResumeMode {
        NONE, RESUME, RECONCILE_ONLY
    }

    /** What the caller should do next, decided by the AI service. {@code OPERATOR_RECONCILE} means stop and escalate. */
    public enum Next {
        WAIT, FETCH_RESULT, OPERATOR_RECONCILE, RECOVER, NONE
    }

    /** Whether the source material is a synthetic fixture or actual material. */
    public enum SourceKind {
        SYNTHETIC, ACTUAL
    }

    /**
     * How a job executed: {@code REPLAY} of an authored recording (no network) or {@code LIVE} (a real model call, recording kind
     * {@code provider}). The service enforces the pair; a job is live only when the operator pinned it server-side.
     */
    public record Provenance(SourceKind sourceKind, ExecutionMode executionMode) {
    }

    /** The runtime's short machine failure code; never a message. */
    public record Failure(String code) {
    }

    public enum DispatchState {
        PENDING, IN_FLIGHT, IDLE
    }

    public enum Outcome {
        EXITED, BUSY, RUNTIME_ERROR, TRANSPORT_UNKNOWN, RUNTIME_UNAVAILABLE, SERVICE_RESTARTED, CANCELLED
    }

    public record Dispatch(DispatchState state, long dispatchCount, Optional<Outcome> lastOutcome, Optional<String> lastRuntimeCode,
                           Instant updatedAt) {
    }

    public enum DeliveryState {
        AVAILABLE, WITHHELD
    }

    /** The delivery gate as of this response; {@code reason} is a short machine code and is present exactly when withheld. */
    public record Delivery(DeliveryState state, Optional<String> reason) {
        public Delivery {
            Objects.requireNonNull(state, "state");
            Objects.requireNonNull(reason, "reason");
            if ((state == DeliveryState.WITHHELD) != reason.isPresent()) {
                throw new IllegalArgumentException("a delivery reason is present exactly when the delivery is withheld");
            }
        }
    }

    /** Per-call accounting metadata only: stage, state and verdict codes. No request, response, digest or content. */
    public record Receipt(String stage, String state, Optional<String> verdict) {
    }

    /** A 2xx answer to a mutating job request: the service durably took it. Not completion, approval or publication. */
    public enum Disposition {
        /** Submit, HTTP 202: registered now. */
        NEWLY_ACCEPTED,
        /** Submit, HTTP 200: the same key and body as an already accepted job; nothing new was registered. */
        ALREADY_ACCEPTED,
        /** Recover, HTTP 202: a new resume dispatch was queued. */
        RECOVERY_ENQUEUED,
        /** Recover, HTTP 200: a dispatch was already pending or running; the request was coalesced. */
        RECOVERY_COALESCED
    }
}
