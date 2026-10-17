package com.zoop.admin.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record AdminLoginRequest(@NotBlank String email, @NotNull String password) {
    @Override
    public String toString() {
        return "AdminLoginRequest[credentials=<redacted>]";
    }
}
