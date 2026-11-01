package com.zoop.ai.round;

import java.util.Optional;

/**
 * ai/service's round-run family (#387 ①, contract proposal of 2026-10-30 agreed by the AI side): one request starts the AI tick
 * and plan-round for an app slot, one read tells how far it got. The app passes its own slot id; the AI side answers with the
 * ingestion round id its tick made, which the freeze request needs.
 */
public interface RoundRunClient {

    /** Send the immutable journal's original POST bytes with the same round identity. */
    RoundRun requestRun(String roundId, byte[] body);

    /** {@code GET /internal/v1/round-runs/{roundId}}. */
    RoundRun runStatus(String roundId);

    /**
     * One round run as the service reports it.
     *
     * @param ingestionRoundId the AI ingestion round the tick made ({@code slot-…}); present from {@code ready} on, and for
     *                         {@code no_new_material} when a round was opened but held nothing new
     * @param planId           the admitted plan of the round ({@code ready} only), with its digest
     * @param code             the service's reason for {@code no_new_material} ({@code outside_operating_window}, ...) or
     *                         {@code failed}
     */
    record RoundRun(String roundId, State state, Optional<String> ingestionRoundId, Optional<String> planId,
            Optional<String> planDigest, Optional<String> code) {

        public enum State {
            RUNNING("running"), READY("ready"), NO_NEW_MATERIAL("no_new_material"), FAILED("failed");

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
