package com.zoop.chat.dto;

/** OpenAPI {@code ChatFailure}: why a job failed and what a retry would do ({@code rerun}, {@code save_only} or null). */
public record ChatFailure(String kind, String reason, String message, String retry) {
}
