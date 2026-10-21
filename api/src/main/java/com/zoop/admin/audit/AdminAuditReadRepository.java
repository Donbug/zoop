package com.zoop.admin.audit;

import java.time.Instant;
import java.util.List;

public interface AdminAuditReadRepository {
    List<AuditRecord> page(String action, String actor, String targetType, String query,
            Instant asOf, Instant afterAt, Long afterId, int limit);
}
