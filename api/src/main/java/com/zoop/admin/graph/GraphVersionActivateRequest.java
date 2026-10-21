package com.zoop.admin.graph;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** {@code expectedActiveVersionId} is the active version the admin saw (null when none was active). */
public record GraphVersionActivateRequest(
        @NotBlank @Size(max = 1000) String reason,
        @Size(max = 120) String expectedActiveVersionId) {
}
