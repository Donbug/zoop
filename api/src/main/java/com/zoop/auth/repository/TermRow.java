package com.zoop.auth.repository;

public record TermRow(
        String id,
        String title,
        boolean required,
        String version,
        String body
) {
}
