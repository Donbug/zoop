package com.zoop.auth.repository;

import java.time.Instant;
import java.util.Optional;

public interface MemberAuthRepository {
    Optional<MemberAuthRow> findByEmailKey(String emailKey);

    void insertEmailMember(String id, String analyticsKey, String email,
            String emailKey, String displayName, String passwordHash, Instant createdAt);
}
