package com.zoop.graph.delivery;

/** A redacted operator outcome; unknown transaction outcomes require reconciliation. */
public final class GraphDeliveryException extends RuntimeException {
    private final String code;

    public GraphDeliveryException(String code) {
        super(code, null, false, false);
        this.code = code;
    }

    public String code() { return code; }
}
