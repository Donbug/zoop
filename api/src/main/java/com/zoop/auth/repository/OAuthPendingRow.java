package com.zoop.auth.repository;

import java.time.Instant;

public record OAuthPendingRow(
        String id,
        String tokenHash,
        String authFlow,
        Instant createdAt,
        Instant expiresAt) {
}
