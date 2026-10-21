package com.zoop.admin.members.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record MemberStatusRequest(
        @Min(1) long expectedRevision,
        @NotBlank @Size(max = 1000) String reason) {
}
