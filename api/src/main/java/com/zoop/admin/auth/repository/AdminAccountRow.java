package com.zoop.admin.auth.repository;

import java.time.Instant;

public record AdminAccountRow(
        String id,
        String email,
        String emailKey,
        String displayName,
        String passwordHash,
        String externalSubject,
        String role,
        String status,
        Instant createdAt) {
}
