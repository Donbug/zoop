package com.zoop.auth.repository;

import java.time.Instant;
import java.util.Optional;

public interface MemberSessionRepository {
    Optional<MemberSessionRow> findByTokenHash(String tokenHash);

    void insertMemberSession(String id, String memberId, String tokenHash,
            String csrfKeyId, Instant createdAt, Instant expiresAt);

    void insertGuestSession(String id, String analyticsKey, String tokenHash,
            String csrfKeyId, Instant createdAt, Instant expiresAt);

    void revokeMemberSession(String tokenHash, String memberId, Instant at);

    void revokeGuestSession(String tokenHash, Instant at);
}
