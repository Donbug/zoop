package com.zoop.ai.extraction;

import java.util.List;
import java.util.Objects;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * Result envelope of one S2 job. The candidates are delivered only while {@code delivery.state=AVAILABLE}, which the service
 * grants only when the job is ready, the operator approval and fixture bytes are still the ones the job was reserved with, and
 * every document's source right is current at this response. Otherwise the state is {@code WITHHELD}, there is no payload, and
 * only content-free {@code receipts} remain.
 */
public record ExtractionResult(ExtractionJobStatus status, PipelineJob.Delivery delivery, Optional<UntrustedExtractionPayload> payload,
                               List<PipelineJob.Receipt> receipts) {

    public ExtractionResult {
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(delivery, "delivery");
        Objects.requireNonNull(payload, "payload");
        receipts = List.copyOf(receipts);
        if ((delivery.state() == PipelineJob.DeliveryState.AVAILABLE) != payload.isPresent()) {
            throw new IllegalArgumentException("payload is present exactly when delivery is available");
        }
    }

    /** The payload only when it is deliverable and the job is {@code READY}. Still untrusted and never a publication. */
    public Optional<UntrustedExtractionPayload> readyPayload() {
        return status.state() == PipelineJob.State.READY ? payload : Optional.empty();
    }
}
