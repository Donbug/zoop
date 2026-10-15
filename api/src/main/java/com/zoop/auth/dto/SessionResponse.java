package com.zoop.auth.dto;

import java.time.Instant;
import java.util.List;

public record SessionResponse(boolean authenticated, String kind, User user, Setup setup,
        Metadata metadata, String csrfToken, Instant expiresAt) {
    public record User(String id, String email, String displayName) {
    }

    public record Setup(boolean completed, boolean tutorialCompleted) {
    }

    public record Metadata(String source, Instant asOf, String graphVersion,
            String requestId, boolean partial, List<Object> failures) {
    }

    public static Metadata metadata(Instant now, String requestId) {
        return new Metadata("zoop", now, null, requestId, false, List.of());
    }

    public static SessionResponse anonymous(Instant now, String requestId) {
        return new SessionResponse(false, "anonymous", null, null,
                metadata(now, requestId), null, null);
    }
}
