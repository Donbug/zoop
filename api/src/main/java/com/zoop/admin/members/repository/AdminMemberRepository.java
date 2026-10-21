package com.zoop.admin.members.repository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface AdminMemberRepository {
    List<MemberSummary> list(String status, String queryId, String queryEmailKey, Instant asOf,
            Instant afterCreatedAt, String afterId, int limit);

    MemberCounts countsAt(Instant asOf);

    Optional<MemberDetailData> findDetail(String memberId, Instant asOf);

    List<MemberActionData> history(String memberId);

    Optional<MemberStatusRow> findStatusForUpdate(String memberId);

    boolean updateStatus(String memberId, long expectedRevision, String targetStatus, Instant blockedAt, Instant now);

    int revokeActiveSessions(String memberId, Instant now);

    boolean claimIdempotency(String id, String adminId, String path, String key,
            String requestHash, Instant createdAt);

    Optional<IdempotencyRow> findIdempotencyForUpdate(String adminId, String path, String key);

    void completeIdempotency(String id, int responseStatus, String responseBody);

    record MemberSummary(String id, String email, String signupMethod, Instant createdAt,
            Instant lastActiveAt, String status, long statusRevision, long sessions) { }

    record MemberCounts(long all, long active, long blocked) { }

    record MemberDetailData(MemberSummary member, boolean onboardingCompleted,
            boolean tutorialCompleted, long watchlistCount, boolean accountConnected) { }

    record MemberActionData(Instant at, String action, String reason, String adminEmail) { }

    record MemberStatusRow(String id, String status, long revision) { }

    record IdempotencyRow(String id, String requestHash, String status,
            Integer responseStatus, String responseBody) { }
}
