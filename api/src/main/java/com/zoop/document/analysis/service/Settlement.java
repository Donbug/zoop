package com.zoop.document.analysis.service;

/** What a committed settlement did. {@code executionsExisting} are attempts that were already counted (never counted twice). */
public record Settlement(String status, String reason, int executionsCreated, int executionsExisting, int evidence) {
}
