package com.zoop.admin.members.service;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.zoop.admin.members.dto.MemberAdminResponse.MemberAction;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberActivity;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberCounts;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberDetail;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberList;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberRow;
import com.zoop.admin.members.repository.AdminMemberRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Service
public class AdminMemberQueryService {
    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 100;
    private static final String UNAVAILABLE = "이 활동 지표는 현재 수집하지 않아 제공되지 않습니다.";

    private final AdminMemberRepository repository;
    private final ObjectMapper mapper;
    private final Clock clock;

    public AdminMemberQueryService(AdminMemberRepository repository, ObjectMapper mapper, Clock clock) {
        this.repository = repository;
        this.mapper = mapper;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public MemberList list(String status, String query, String cursor, Integer requestedLimit, String requestId) {
        String normalizedStatus = normalizeStatus(status);
        String queryValue = normalizeQuery(query);
        String queryEmailKey = queryValue != null && queryValue.contains("@")
                ? queryValue.toLowerCase(Locale.ROOT) : queryValue;
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String filterHash = Canonical.sha256((normalizedStatus == null ? "" : normalizedStatus)
                + "\n" + (queryEmailKey == null ? "" : queryEmailKey));
        var position = MemberListCursor.decode(mapper, cursor, filterHash, requestedLimit);
        int limit = requestedLimit != null ? requestedLimit
                : position == null ? DEFAULT_LIMIT : position.limit();
        Instant asOf = position == null ? clock.instant() : position.asOf();
        if (asOf.isAfter(clock.instant())) throw new CustomException(ErrorCode.INVALID_CURSOR);
        try {
            var rows = repository.list(normalizedStatus, queryValue, queryEmailKey, asOf,
                    position == null ? null : position.createdAt(), position == null ? null : position.id(), limit + 1);
            boolean hasNext = rows.size() > limit;
            var pageRows = hasNext ? rows.subList(0, limit) : rows;
            List<MemberRow> items = pageRows.stream().map(this::row).toList();
            String nextCursor = null;
            if (hasNext) {
                var last = pageRows.get(pageRows.size() - 1);
                nextCursor = MemberListCursor.encode(mapper, filterHash, limit, asOf, last.createdAt(), last.id());
            }
            var counts = repository.countsAt(asOf);
            return new MemberList(items, nextCursor,
                    new MemberCounts(counts.all(), counts.active(), counts.blocked()),
                    metadata(asOf, requestId, activityFailures(asOf)));
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    @Transactional(readOnly = true)
    public MemberDetail detail(String memberId, String requestId) {
        return detailAt(memberId, clock.instant(), requestId);
    }

    MemberDetail detailAt(String memberId, Instant asOf, String requestId) {
        try {
            var data = repository.findDetail(memberId, asOf)
                    .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            var history = repository.history(memberId).stream().map(action -> new MemberAction(
                    action.at(), action.action(), action.reason(), action.adminEmail())).toList();
            List<SectionFailure> failures = new ArrayList<>(activityFailures(asOf));
            failures.add(unavailable("holdingCount", asOf));
            failures.add(unavailable("feedbackUp", asOf));
            failures.add(unavailable("feedbackDown", asOf));
            return new MemberDetail(row(data.member()), data.onboardingCompleted(), data.tutorialCompleted(),
                    data.watchlistCount(), null, data.accountConnected(), null, null, history,
                    metadata(asOf, requestId, failures));
        } catch (CustomException exception) {
            throw exception;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private MemberRow row(AdminMemberRepository.MemberSummary row) {
        return new MemberRow(row.id(), maskEmail(row.email()), row.signupMethod(), row.createdAt(),
                row.lastActiveAt(), row.status(), row.statusRevision(),
                new MemberActivity(row.sessions(), null, null, null));
    }

    private static Metadata metadata(Instant asOf, String requestId, List<SectionFailure> failures) {
        return new Metadata("zoop-db", asOf, null, requestId, !failures.isEmpty(), List.copyOf(failures));
    }

    private static List<SectionFailure> activityFailures(Instant asOf) {
        return List.of(unavailable("activity.graphSelections", asOf),
                unavailable("activity.aiQuestions", asOf), unavailable("activity.briefingViews", asOf));
    }

    private static SectionFailure unavailable(String section, Instant asOf) {
        return new SectionFailure(section, "SOURCE_UNAVAILABLE", UNAVAILABLE, false, asOf);
    }

    private static String normalizeStatus(String status) {
        if (status == null || status.isBlank()) return null;
        String normalized = status.strip().toLowerCase(Locale.ROOT);
        if (!normalized.equals("active") && !normalized.equals("blocked")) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return normalized;
    }

    private static String normalizeQuery(String query) {
        if (query == null || query.isBlank()) return null;
        String normalized = query.strip();
        if (normalized.length() > 254 || normalized.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return normalized;
    }

    static String maskEmail(String email) {
        int at = email.indexOf('@');
        if (at <= 0 || at == email.length() - 1) return "***";
        String local = email.substring(0, at);
        String visible = local.length() == 1 ? "*" : local.substring(0, 1) + "***";
        return visible + email.substring(at);
    }
}
