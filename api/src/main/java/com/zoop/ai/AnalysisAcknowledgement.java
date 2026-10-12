package com.zoop.ai;

import java.util.Objects;

/**
 * A 2xx answer to a mutating request. It says the AI service durably took the request; it does not say the job ran, was
 * authorized, budgeted or completed. Poll {@code status} and follow {@code status.next()}.
 */
public record AnalysisAcknowledgement(Disposition disposition, AnalysisJobStatus status) {

    public AnalysisAcknowledgement {
        Objects.requireNonNull(disposition, "disposition");
        Objects.requireNonNull(status, "status");
    }

    public enum Disposition {
        /** Submit, HTTP 202: registered now; owner binding and dispatch intent are durable. */
        NEWLY_ACCEPTED,
        /** Submit, HTTP 200: same key and body as an already accepted job; nothing new was registered. */
        ALREADY_ACCEPTED,
        /** Recover, HTTP 202: a new run/resume dispatch was queued. */
        RECOVERY_ENQUEUED,
        /** Recover, HTTP 200: a dispatch was already pending or running; the request was coalesced. */
        RECOVERY_COALESCED
    }
}
