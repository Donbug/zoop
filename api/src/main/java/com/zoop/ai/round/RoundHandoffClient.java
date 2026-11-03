package com.zoop.ai.round;

import java.util.Objects;
import java.util.Optional;

import tools.jackson.databind.JsonNode;

/**
 * ai/service's round-handoff family (#387 ②, contract proposal of 2026-10-30): one request asks the AI side to freeze the
 * cumulative bundle for an app slot ({@code freeze-round}: the S3 job window recomputed from its ledgers, the operator files
 * narrowed to it), one read tells whether the handoff is ready. The request carries the app's document bindings (every
 * registered version, {@code zoop-app-document-bindings-1}) because they are an input of the freeze and the window is not known
 * before it. A request without a plan is a carry-only freeze (a slot without new material, or the freeze-only slot after the
 * operating hours).
 */
public interface RoundHandoffClient {

    /** Send the immutable journal's original POST bytes with the same round identity. */
    RoundHandoff requestHandoff(String roundId, byte[] body);

    /** {@code GET /internal/v1/round-handoffs/{roundId}}. */
    RoundHandoff handoffStatus(String roundId);

    /**
     * @param ingestionRoundId the AI ingestion round the slot's run made, when there was one (the freeze-only slot has none)
     * @param planId           the admitted plan of the slot, when there was one
     * @param bindings         the exact bytes of the app's bindings export ({@code zoop-app-document-bindings-1}, one JSON object)
     */
    record Request(String roundId, Optional<String> ingestionRoundId, Optional<String> planId, byte[] bindings) {
        public Request {
            Objects.requireNonNull(roundId, "roundId");
            Objects.requireNonNull(ingestionRoundId, "ingestionRoundId");
            Objects.requireNonNull(planId, "planId");
            Objects.requireNonNull(bindings, "bindings");
        }
    }

    /**
     * One round handoff as the service reports it.
     *
     * @param handoffId      the frozen handoff ({@code hr-…}, derived from the manifest content) with its two digests, {@code ready} only
     * @param selection      the producer's selection report; status and exclusion-reason counts are recorded on the timeline
     * @param code           the service's reason for {@code analysis_incomplete}, {@code no_public_material} or {@code failed}
     */
    record RoundHandoff(String roundId, State state, Optional<String> handoffId, Optional<String> manifestDigest,
            Optional<String> bundleDigest, Optional<JsonNode> selection, Optional<String> code) {

        public enum State {
            RUNNING("running"), READY("ready"), ANALYSIS_INCOMPLETE("analysis_incomplete"),
            NO_PUBLIC_MATERIAL("no_public_material"), FAILED("failed");

            private final String wire;

            State(String wire) {
                this.wire = wire;
            }

            public String wire() {
                return wire;
            }

            public static Optional<State> parse(String wire) {
                for (State state : values()) {
                    if (state.wire.equals(wire)) return Optional.of(state);
                }
                return Optional.empty();
            }
        }
    }
}
