package com.zoop.ai;

import java.util.Arrays;
import java.util.Optional;

/** How the AI runtime executes a job. {@code LIVE} is a server-side decision the service may refuse (409 execution_unavailable). */
public enum ExecutionMode {
    REPLAY("replay"),
    LIVE("live");

    private final String wire;

    ExecutionMode(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static Optional<ExecutionMode> fromWire(String value) {
        return Arrays.stream(values()).filter(mode -> mode.wire.equals(value)).findFirst();
    }
}
