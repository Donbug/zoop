package com.zoop.auth.repository;

import java.time.Instant;
import java.util.Optional;

public interface MemberAuthRepository {
    Optional<MemberAuthRow> findByEmailKey(String emailKey);

    Optional<MemberAuthRow> findById(String id);

    Optional<MemberLinkTargetRow> findLinkTargetById(String id);

    boolean insertSocialMember(String id, String analyticsKey, String email, String emailKey,
            String displayName, String signupProvider, Instant createdAt);

    void insertEmailMember(String id, String analyticsKey, String email,
            String emailKey, String displayName, String passwordHash, Instant createdAt);
}
