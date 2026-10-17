package com.zoop.admin.auth.repository;

import java.time.Instant;

/** Session state joined to the current administrator authority. */
public record AdminSessionRow(
        String id,
        String adminId,
        String tokenHash,
        String csrfKeyId,
        long csrfVersion,
        Instant createdAt,
        Instant lastSeenAt,
        Instant idleExpiresAt,
        Instant expiresAt,
        Instant revokedAt,
        String email,
        String displayName,
        String role,
        String adminStatus) {
}
