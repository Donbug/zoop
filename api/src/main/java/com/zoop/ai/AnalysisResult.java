package com.zoop.ai;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/**
 * Result envelope of one job. The content is delivered only while {@code delivery.state=AVAILABLE}; when the server's
 * current source rights forbid delivery the state is {@code WITHHELD}, there is no payload, and only content-free
 * {@code receipts} for usage accounting remain. A withheld result is never available.
 */
public record AnalysisResult(AnalysisJobStatus status, Delivery delivery, Optional<UntrustedAnalysisPayload> payload,
                             List<Receipt> receipts) {

    public AnalysisResult {
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(delivery, "delivery");
        Objects.requireNonNull(payload, "payload");
        receipts = List.copyOf(receipts);
        if ((delivery.state() == Delivery.State.AVAILABLE) != payload.isPresent()) {
            throw new IllegalArgumentException("payload is present exactly when delivery is available");
        }
    }

    /**
     * The payload only when it is both deliverable and the job is internally {@code READY}. Still untrusted and not a
     * publication: see {@link UntrustedAnalysisPayload}.
     */
    public Optional<UntrustedAnalysisPayload> readyPayload() {
        return status.state() == AnalysisJobStatus.State.READY ? payload : Optional.empty();
    }

    /** {@code reason} is a short machine code and is present exactly when the state is {@code WITHHELD}. */
    public record Delivery(State state, Optional<String> reason) {
        public enum State {
            AVAILABLE, WITHHELD
        }
    }

    /** Per-attempt accounting metadata. It carries no provider receipt, request or response content. */
    public record Receipt(String attemptId, AnalysisKind stage, CallState state, ExecutionMode mode, Instant startedAt,
                          Optional<Instant> receivedAt, String inputDigest, Optional<Tokens> tokens, Optional<String> error,
                          Optional<Double> durationMs, String provider, String providerRevision, String model,
                          Optional<String> reasoningEffort, String promptVersion, String schemaVersion, String policyVersion) {

        public enum CallState {
            STARTED, RECEIVED, VALIDATED, FAILED, UNKNOWN
        }

        public record Tokens(Long inputTokens, Long outputTokens, Long cachedTokens, Long reasoningTokens) {
        }
    }
}
