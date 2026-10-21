package com.zoop.admin.audit;

import java.time.Instant;

/** Database row after SQL has applied the public reason policy. */
public record AuditRecord(long id, Instant at, String actorKind, String actorId,
        String actorEmail, String action, String targetType, String targetId,
        String reason, String outcome, String detailJson) { }
