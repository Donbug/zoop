package com.zoop.admin.audit;

import java.time.Instant;
import java.util.List;
import java.util.Map;

public record AuditPage(List<AuditEntry> items, String nextCursor) {
    public record AuditEntry(long id, Instant at, String actorKind, String actorId,
            String actorEmail, String action, String targetType, String targetId,
            String reason, String outcome, Map<String, Object> detail) { }
}
