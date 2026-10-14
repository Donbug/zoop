package com.zoop.document.service;

import java.time.Instant;

/**
 * What one registration did. {@code collectedAt} is the stored value, which is the first registered observation's, not
 * necessarily this item's; {@code currentVersion} is the pointer as it is after the transaction.
 */
public record RegistrationOutcome(Presence article, Presence artifact, Presence version, PointerResult pointer,
        String currentVersion, Instant collectedAt) {

    public enum Presence {
        CREATED("created"), EXISTING("existing");

        private final String wire;

        Presence(String wire) {
            this.wire = wire;
        }

        public String wire() {
            return wire;
        }

        public static Presence of(boolean created) {
            return created ? CREATED : EXISTING;
        }
    }

    public enum PointerResult {
        UNCHANGED("unchanged"), MOVED("moved"), ALREADY_CURRENT("already-current");

        private final String wire;

        PointerResult(String wire) {
            this.wire = wire;
        }

        public String wire() {
            return wire;
        }
    }
}
