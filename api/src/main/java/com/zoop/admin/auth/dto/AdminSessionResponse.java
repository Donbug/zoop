package com.zoop.admin.auth.dto;

import java.time.Instant;

public record AdminSessionResponse(boolean authenticated, boolean expired,
        String expiredReason, AdminInfo admin, Instant expiresAt, Instant idleExpiresAt,
        int idleTimeoutSeconds, int absoluteTimeoutSeconds, String csrfToken) {
    public static AdminSessionResponse anonymous(boolean expired, String reason,
            int idleTimeoutSeconds, int absoluteTimeoutSeconds) {
        return new AdminSessionResponse(false, expired, reason, null, null, null,
                idleTimeoutSeconds, absoluteTimeoutSeconds, null);
    }
}
