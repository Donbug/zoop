package com.zoop.admin.auth.repository;

import java.time.Instant;
import java.util.Optional;

public interface AdminAuthRepository {
    Optional<AdminAccountRow> findAccountByEmailKey(String emailKey);

    boolean insertPasswordAccount(String id, String email, String emailKey,
            String displayName, String passwordHash, Instant createdAt);

    Optional<AdminSessionRow> findSessionByTokenHash(String tokenHash);

    boolean insertSession(String id, String adminId, String tokenHash, String csrfKeyId,
            Instant createdAt, Instant idleExpiresAt, Instant expiresAt);

    boolean touchSession(String id, Instant seenAt, Instant idleExpiresAt);

    boolean revokeSession(String tokenHash, String adminId, Instant revokedAt);
}
