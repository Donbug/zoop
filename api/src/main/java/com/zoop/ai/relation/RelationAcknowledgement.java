package com.zoop.ai.relation;

import java.util.Objects;

import com.zoop.ai.PipelineJob;

/** A 2xx answer to a mutating S3 job request: the service durably took it. Poll {@code status} and follow {@code status.next()}. */
public record RelationAcknowledgement(PipelineJob.Disposition disposition, RelationJobStatus status) {

    public RelationAcknowledgement {
        Objects.requireNonNull(disposition, "disposition");
        Objects.requireNonNull(status, "status");
    }
}
