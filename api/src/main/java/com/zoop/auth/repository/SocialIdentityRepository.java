package com.zoop.auth.repository;

import java.time.Instant;
import java.util.Optional;

public interface SocialIdentityRepository {
    Optional<SocialIdentityRow> findByProviderSubject(String provider, String providerSubject);

    void insert(String id, String memberId, String provider, String providerSubject, Instant linkedAt);
}
