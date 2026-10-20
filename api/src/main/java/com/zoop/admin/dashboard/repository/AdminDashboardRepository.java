package com.zoop.admin.dashboard.repository;

import java.time.Instant;
import java.util.Optional;

import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardActiveGraphVersion;

public interface AdminDashboardRepository {
    MemberCounts memberCountsAt(Instant asOf);

    long auditCountBetween(Instant startInclusive, Instant endExclusive);

    GraphSummary graphSummaryAt(Instant asOf);

    record MemberCounts(long registered, long activeMemberSessions, long activeGuestSessions) { }

    record GraphSummary(long versionCount, Optional<DashboardActiveGraphVersion> activeVersion) { }
}
