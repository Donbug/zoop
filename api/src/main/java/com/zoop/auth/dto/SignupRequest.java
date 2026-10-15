package com.zoop.auth.dto;

import java.util.List;
import jakarta.validation.constraints.NotBlank;

public record SignupRequest(@NotBlank String email, String password, String displayName,
        List<Agreement> agreements) {
    @Override
    public String toString() {
        return "SignupRequest[credentials=<redacted>]";
    }

    public record Agreement(String id, String version, Boolean accepted) {
    }
}
