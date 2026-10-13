package com.zoop.auth.dto;

public record TermOut(
        String title,
        String body,
        String version,
        String id,
        boolean required,
        boolean bodyAvailable
) {
}
