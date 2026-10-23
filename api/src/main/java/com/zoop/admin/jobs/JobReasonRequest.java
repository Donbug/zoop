package com.zoop.admin.jobs;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** OpenAPI {@code JobRetry} and {@code ReasonRequest}: both are a required, non-blank reason that the audit log keeps. */
public record JobReasonRequest(@NotBlank @Size(max = 500) String reason) {
}
