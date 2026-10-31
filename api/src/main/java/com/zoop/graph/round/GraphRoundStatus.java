package com.zoop.graph.round;

import java.time.Instant;
import java.util.Optional;

/**
 * What the round scheduler says about itself for the admin overview. Without a scheduler bean (the feature off, or this
 * release, which holds the import bridge only) the status is {@link #DISABLED}.
 */
public interface GraphRoundStatus {
    GraphRoundStatus DISABLED = new GraphRoundStatus() {
        @Override
        public boolean enabled() {
            return false;
        }

        @Override
        public Optional<Instant> nextSlotAt() {
            return Optional.empty();
        }

        @Override
        public Optional<Instant> lastTickAt() {
            return Optional.empty();
        }
    };

    boolean enabled();

    /** The next slot the scheduler will open. */
    Optional<Instant> nextSlotAt();

    /** When the scheduler last ran. */
    Optional<Instant> lastTickAt();
}
