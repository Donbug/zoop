package com.zoop.telemetry.entity;

import java.io.Serializable;
import java.util.Objects;

public class TelemetryBatchId implements Serializable {
    private String principalKey;
    private String idempotencyKey;

    public TelemetryBatchId() {
    }

    public TelemetryBatchId(String principalKey, String idempotencyKey) {
        this.principalKey = principalKey;
        this.idempotencyKey = idempotencyKey;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) return true;
        if (!(other instanceof TelemetryBatchId that)) return false;
        return Objects.equals(principalKey, that.principalKey)
                && Objects.equals(idempotencyKey, that.idempotencyKey);
    }

    @Override
    public int hashCode() {
        return Objects.hash(principalKey, idempotencyKey);
    }
}
