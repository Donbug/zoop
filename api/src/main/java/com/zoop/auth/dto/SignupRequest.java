package com.zoop.auth.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;

public record SignupRequest(@NotBlank String email,
        @Schema(minLength = 8, maxLength = 32) String password, String displayName,
        List<Agreement> agreements) {
    @Override
    public String toString() {
        return "SignupRequest[credentials=<redacted>]";
    }

    public record Agreement(String id, String version, Boolean accepted) {
    }
}
