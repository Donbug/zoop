package com.zoop.ai.extraction;

import java.util.Objects;

import com.zoop.ai.PipelineJob;

/** A 2xx answer to a mutating S2 request: the service durably took it. Poll {@code status} and follow {@code status.next()}. */
public record ExtractionAcknowledgement(PipelineJob.Disposition disposition, ExtractionJobStatus status) {

    public ExtractionAcknowledgement {
        Objects.requireNonNull(disposition, "disposition");
        Objects.requireNonNull(status, "status");
    }
}
