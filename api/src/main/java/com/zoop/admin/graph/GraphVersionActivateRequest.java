package com.zoop.admin.graph;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * {@code expectedActiveVersionId} is the active version the admin saw. The contract makes it required but nullable: a body
 * without the field fails to bind ({@code required = true}, 422 INVALID_REQUEST), while an explicit JSON {@code null} binds as
 * {@code null} and means none was active.
 */
public record GraphVersionActivateRequest(
        @NotBlank @Size(max = 1000) String reason,
        @JsonProperty(required = true) @Size(max = 120) String expectedActiveVersionId,
        @Pattern(regexp = "forward|rollback") String mode) {
    public GraphVersionActivateRequest {
        if (mode == null) mode = "forward";
    }
}
