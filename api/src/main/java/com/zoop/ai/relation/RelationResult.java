package com.zoop.ai.relation;

import java.util.List;
import java.util.Objects;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/**
 * Result envelope of one S3 job. The candidates are delivered only while {@code delivery.state=AVAILABLE}, which the service
 * grants only when the job is ready, the pipeline's delivery gate is current (source registry, ingestion binding, the exact S2
 * export) and the operator's upstream allowlist still lists the owner. Otherwise the state is {@code WITHHELD}, there is no
 * payload, and only content-free {@code receipts} remain.
 */
public record RelationResult(RelationJobStatus status, PipelineJob.Delivery delivery, Optional<UntrustedRelationPayload> payload,
                             List<PipelineJob.Receipt> receipts) {

    public RelationResult {
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(delivery, "delivery");
        Objects.requireNonNull(payload, "payload");
        receipts = List.copyOf(receipts);
        if ((delivery.state() == PipelineJob.DeliveryState.AVAILABLE) != payload.isPresent()) {
            throw new IllegalArgumentException("payload is present exactly when delivery is available");
        }
    }

    /** The payload only when it is deliverable and the job is {@code READY}. Still untrusted and never a publication. */
    public Optional<UntrustedRelationPayload> readyPayload() {
        return status.state() == PipelineJob.State.READY ? payload : Optional.empty();
    }
}
