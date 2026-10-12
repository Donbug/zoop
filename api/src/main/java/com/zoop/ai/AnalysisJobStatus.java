package com.zoop.ai;

import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;

/**
 * Content-free job status exactly as the AI service observed it for this request ({@code JobStatus}, schema
 * {@code zoop-ai-internal-1}). {@code state=READY} is internal readiness, not the app's public {@code completed}; the app's own
 * import and authority checks still decide that. Cost fields are reported as the runtime knows them: {@code usage} and
 * {@code unreceiptedAttempts} are never rewritten, and a cancelled job can still receive late receipts.
 */
public record AnalysisJobStatus(
        String jobId,
        AnalysisKind kind,
        ExecutionMode mode,
        String inputDigest,
        State state,
        String phase,
        ResumeMode resumeMode,
        Failure failure,
        List<String> artifactIds,
        Usage usage,
        int unreceiptedAttempts,
        Dispatch dispatch,
        Next next,
        Instant acceptedAt,
        Instant observedAt,
        Optional<Duration> retryAfter) {

    public AnalysisJobStatus {
        artifactIds = List.copyOf(artifactIds);
    }

    public enum State implements Wire {
        QUEUED("queued"), RUNNING("running"), RECONCILING("reconciling"), PERSISTING("persisting"), READY("ready"),
        FAILED("failed"), CANCELLED("cancelled");

        private final String wire;

        State(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }

        public static Optional<State> fromWire(String value) {
            return Wire.find(values(), value);
        }
    }

    public enum ResumeMode implements Wire {
        NONE("none"), VALIDATE_ONLY("validate_only"), SAVE_ONLY("save_only"), UNSENT_ONLY("unsent_only"),
        RECONCILE_ONLY("reconcile_only");

        private final String wire;

        ResumeMode(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }

        public static Optional<ResumeMode> fromWire(String value) {
            return Wire.find(values(), value);
        }
    }

    /** What the caller should do next, decided by the AI service. {@code OPERATOR_RECONCILE} means stop and escalate. */
    public enum Next implements Wire {
        WAIT("wait"), FETCH_RESULT("fetch_result"), OPERATOR_RECONCILE("operator_reconcile"), RECOVER("recover"), NONE("none");

        private final String wire;

        Next(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }

        public static Optional<Next> fromWire(String value) {
            return Wire.find(values(), value);
        }
    }

    public record Failure(String code, Optional<AnalysisKind> stage) {
    }

    /** Provider tokens are null when the runtime has no count; {@code cost} is whatever the runtime computed, or null. */
    public record Usage(long providerAttempts, long replayCalls, Long inputTokens, Long outputTokens, Long cachedTokens,
                        Long reasoningTokens, Double cost) {
    }

    public record Dispatch(DispatchState state, Optional<Command> command, long dispatchCount, Optional<Outcome> lastOutcome,
                           Optional<String> lastRuntimeCode, Instant updatedAt) {

        public enum DispatchState implements Wire {
            PENDING("pending"), IN_FLIGHT("in_flight"), IDLE("idle");

            private final String wire;

            DispatchState(String wire) {
                this.wire = wire;
            }

            @Override
            public String wire() {
                return wire;
            }

            public static Optional<DispatchState> fromWire(String value) {
                return Wire.find(values(), value);
            }
        }

        public enum Command implements Wire {
            RUN("run"), RESUME("resume");

            private final String wire;

            Command(String wire) {
                this.wire = wire;
            }

            @Override
            public String wire() {
                return wire;
            }

            public static Optional<Command> fromWire(String value) {
                return Wire.find(values(), value);
            }
        }

        public enum Outcome implements Wire {
            EXITED("exited"), BUSY("busy"), RUNTIME_ERROR("runtime_error"), TRANSPORT_UNKNOWN("transport_unknown"),
            RUNTIME_UNAVAILABLE("runtime_unavailable"), SERVICE_RESTARTED("service_restarted"), CANCELLED("cancelled"),
            NEEDS_RECOVER("needs_recover");

            private final String wire;

            Outcome(String wire) {
                this.wire = wire;
            }

            @Override
            public String wire() {
                return wire;
            }

            public static Optional<Outcome> fromWire(String value) {
                return Wire.find(values(), value);
            }
        }
    }

    /** Enum wire-name lookup shared by the nested enums. */
    interface Wire {
        String wire();

        static <E extends Wire> Optional<E> find(E[] values, String wire) {
            return Arrays.stream(values).filter(value -> value.wire().equals(wire)).findFirst();
        }
    }
}
