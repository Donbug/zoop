package com.zoop.admin.members;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import com.zoop.admin.members.repository.AdminMemberRepository;
import com.zoop.admin.members.repository.AdminMemberRepository.MemberCounts;
import com.zoop.admin.members.repository.AdminMemberRepository.MemberDetailData;
import com.zoop.admin.members.repository.AdminMemberRepository.MemberSummary;
import com.zoop.admin.members.service.AdminMemberQueryService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AdminMemberQueryServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-20T00:00:00Z");

    @Mock AdminMemberRepository repository;

    @Test
    void listsMaskedMembersAndKeepsUnavailableMetricsDistinctFromZero() {
        var member = new MemberSummary("opaque-member", "member@example.com", "email",
                NOW.minusSeconds(100), NOW.minusSeconds(50), "active", 2, 0);
        when(repository.list(isNull(), eq("Member@Example.com"), eq("member@example.com"),
                eq(NOW), isNull(), isNull(), eq(51)))
                .thenReturn(List.of(member));
        when(repository.countsAt(NOW)).thenReturn(new MemberCounts(1, 1, 0));

        var response = service().list(null, " Member@Example.com ", null, null, "request-1");

        assertEquals(1, response.items().size());
        assertEquals("m***@example.com", response.items().getFirst().emailMasked());
        assertEquals(0, response.items().getFirst().activity().sessions());
        assertNull(response.items().getFirst().activity().aiQuestions());
        assertTrue(response.metadata().partial());
        assertTrue(response.metadata().failures().stream()
                .anyMatch(failure -> failure.section().equals("activity.aiQuestions")));
        assertNull(response.nextCursor());
    }

    @Test
    void cursorIsBoundToFiltersAndLimit() {
        var first = new MemberSummary("member-2", "two@example.com", "email",
                NOW.minusSeconds(20), null, "active", 1, 0);
        var second = new MemberSummary("member-1", "one@example.com", "email",
                NOW.minusSeconds(30), null, "active", 1, 0);
        when(repository.list(eq("active"), isNull(), isNull(), eq(NOW), isNull(), isNull(), eq(2)))
                .thenReturn(List.of(first, second));
        when(repository.countsAt(NOW)).thenReturn(new MemberCounts(2, 2, 0));
        var service = service();

        var page = service.list("active", null, null, 1, "request-1");
        assertEquals(1, page.items().size());
        assertFalse(page.nextCursor().isBlank());

        CustomException mismatch = assertThrows(CustomException.class,
                () -> service.list("blocked", null, page.nextCursor(), 1, "request-2"));
        assertEquals(ErrorCode.INVALID_CURSOR, mismatch.getErrorCode());
    }

    @Test
    void detailsNeverInventUnavailableCounts() {
        var summary = new MemberSummary("member-1", "one@example.com", "google",
                NOW.minusSeconds(100), NOW.minusSeconds(10), "blocked", 3, 4);
        when(repository.findDetail("member-1", NOW))
                .thenReturn(Optional.of(new MemberDetailData(summary, true, false, 2, true)));
        when(repository.history("member-1")).thenReturn(List.of());

        var detail = service().detail("member-1", "request-detail");

        assertEquals(2, detail.watchlistCount());
        assertTrue(detail.accountConnected());
        assertNull(detail.holdingCount());
        assertNull(detail.feedbackUp());
        assertTrue(detail.metadata().failures().stream()
                .anyMatch(failure -> failure.section().equals("holdingCount")
                        && failure.message().contains("제공되지 않습니다") && !failure.retryable()));
    }

    @Test
    void mapsDatabaseFailureToSourceUnavailable() {
        when(repository.list(any(), any(), any(), any(), any(), any(), anyInt()))
                .thenThrow(new DataAccessResourceFailureException("offline"));

        CustomException failure = assertThrows(CustomException.class,
                () -> service().list(null, null, null, null, "request-failed"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
    }

    private AdminMemberQueryService service() {
        return new AdminMemberQueryService(repository, JsonMapper.builder().build(),
                Clock.fixed(NOW, ZoneOffset.UTC));
    }
}
