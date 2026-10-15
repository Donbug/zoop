package com.zoop.auth.repository;

import java.time.Instant;

public record SocialIdentityRow(
        String id,
        String memberId,
        String provider,
        String providerSubject,
        Instant linkedAt) {
}
