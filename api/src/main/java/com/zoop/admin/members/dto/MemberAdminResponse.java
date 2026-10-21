package com.zoop.admin.members.dto;

import java.time.Instant;
import java.util.List;

import com.zoop.common.response.Metadata;

public final class MemberAdminResponse {
    private MemberAdminResponse() { }

    public record MemberActivity(Long sessions, Long graphSelections, Long aiQuestions, Long briefingViews) { }

    public record MemberRow(String id, String emailMasked, String signupMethod, Instant createdAt,
            Instant lastActiveAt, String status, long statusRevision, MemberActivity activity) { }

    public record MemberCounts(long all, long active, long blocked) { }

    public record MemberAction(Instant at, String action, String reason, String adminEmail) { }

    public record MemberList(List<MemberRow> items, String nextCursor, MemberCounts counts, Metadata metadata) { }

    public record MemberDetail(MemberRow member, boolean onboardingCompleted, boolean tutorialCompleted,
            long watchlistCount, Long holdingCount, boolean accountConnected,
            Long feedbackUp, Long feedbackDown, List<MemberAction> history, Metadata metadata) { }

    public record MemberStatusResult(boolean changed, MemberDetail detail) { }
}
