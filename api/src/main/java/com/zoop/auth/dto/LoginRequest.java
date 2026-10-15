package com.zoop.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record LoginRequest(@NotBlank String email, @NotNull String password) {
    @Override
    public String toString() {
        return "LoginRequest[credentials=<redacted>]";
    }
}
