package com.zoop.auth.repository;

import java.time.Instant;

public record MemberSessionRow(
        String id, String memberId, String kind, String tokenHash,
        String csrfKeyId, long csrfVersion, Instant createdAt,
        Instant expiresAt, Instant revokedAt, String memberStatus,
        String email, String displayName, boolean completed,
        boolean tutorialCompleted, String analyticsKey) {
}
