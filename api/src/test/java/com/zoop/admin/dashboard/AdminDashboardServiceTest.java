package com.zoop.admin.dashboard;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardActiveGraphVersion;
import com.zoop.admin.dashboard.repository.AdminDashboardRepository;
import com.zoop.admin.dashboard.repository.AdminDashboardRepository.GraphSummary;
import com.zoop.admin.dashboard.repository.AdminDashboardRepository.MemberCounts;
import com.zoop.admin.dashboard.service.AdminDashboardService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.jdbc.BadSqlGrammarException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AdminDashboardServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-20T00:00:00Z");

    @Mock AdminDashboardRepository repository;

    @Test
    void buildsConsistentSnapshotAndMarksUnavailableAreasWithoutInventingZeroes() throws Exception {
        when(repository.memberCountsAt(NOW)).thenReturn(new MemberCounts(12, 3, 2));
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW)).thenReturn(5L);
        when(repository.graphSummaryAt(NOW)).thenReturn(new GraphSummary(2,
                Optional.of(new DashboardActiveGraphVersion("v2", 2, "snapshot", "daily-import",
                        NOW.minusSeconds(300), NOW.minusSeconds(200), 10, 20, 4))));

        var service = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC));
        AdminDashboardResponse response = service.getDashboard("dashboard-request-1");

        assertEquals(NOW, response.generatedAt());
        assertEquals(NOW, response.metadata().asOf());
        assertEquals("admin-dashboard", response.metadata().source());
        assertNull(response.metadata().graphVersion());
        assertEquals("dashboard-request-1", response.metadata().requestId());
        assertTrue(response.metadata().partial());
        assertEquals(12, response.members().registered());
        assertEquals(3, response.members().activeMemberSessions());
        assertEquals(2, response.members().activeGuestSessions());
        assertEquals("zoop-db", response.members().source());
        assertEquals(5, response.audit().last24h());
        assertEquals("v2", response.graph().activeVersionId());
        assertEquals(2, response.graph().versionCount());
        assertNull(response.candidates());
        assertNull(response.jobs());
        assertNull(response.ai());
        assertNull(response.briefings());
        assertTrue(response.metadata().failures().stream().anyMatch(f -> f.section().equals("candidates")));
        assertTrue(response.metadata().failures().stream().anyMatch(f -> f.section().equals("graph.graphDb")));
        String json = new ObjectMapper().findAndRegisterModules().writeValueAsString(response);
        assertTrue(json.contains("\"metadata\""));
        assertTrue(json.contains("\"partial\":true"));
        assertTrue(json.contains("\"graphVersion\":null"));
        assertTrue(json.contains("\"jobs\":null"));
        verify(repository).auditCountBetween(NOW.minusSeconds(86_400), NOW);
    }

    @Test
    void retainsAvailableAreasWhenOneSourceQueryFails() {
        when(repository.memberCountsAt(NOW)).thenThrow(new DataAccessResourceFailureException("db read failed"));
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW)).thenReturn(1L);
        when(repository.graphSummaryAt(NOW)).thenReturn(new GraphSummary(0, Optional.empty()));

        var service = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC));
        AdminDashboardResponse response = service.getDashboard("request-2");

        assertNull(response.members());
        assertEquals(1, response.audit().last24h());
        assertEquals(0, response.graph().versionCount());
        var failure = response.metadata().failures().stream()
                .filter(f -> f.section().equals("members")).findFirst().orElseThrow();
        assertTrue(failure.retryable());
        assertEquals("이 영역을 조회하는 중 오류가 발생했습니다.", failure.message());
    }

    @Test
    void marksNonTransientDatabaseFailuresAsNotRetryable() {
        when(repository.memberCountsAt(NOW)).thenThrow(new BadSqlGrammarException(
                "memberCountsAt", "select broken", new java.sql.SQLException("syntax error")));
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW)).thenReturn(1L);
        when(repository.graphSummaryAt(NOW)).thenReturn(new GraphSummary(0, Optional.empty()));

        var response = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC))
                .getDashboard("request-non-transient");

        var failure = response.metadata().failures().stream()
                .filter(f -> f.section().equals("members")).findFirst().orElseThrow();
        assertFalse(failure.retryable());
        assertEquals("이 영역을 조회하는 중 오류가 발생했습니다.", failure.message());
    }

    @Test
    void marksTransientDatabaseFailuresAsRetryable() {
        when(repository.memberCountsAt(NOW)).thenThrow(new QueryTimeoutException("query timed out"));
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW)).thenReturn(1L);
        when(repository.graphSummaryAt(NOW)).thenReturn(new GraphSummary(0, Optional.empty()));

        var response = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC))
                .getDashboard("request-transient");

        var failure = response.metadata().failures().stream()
                .filter(f -> f.section().equals("members")).findFirst().orElseThrow();
        assertTrue(failure.retryable());
    }

    @Test
    void leavesNotYetConnectedAreasDistinctFromDatabaseReadFailures() {
        when(repository.memberCountsAt(NOW)).thenReturn(new MemberCounts(12, 3, 2));
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW)).thenReturn(1L);
        when(repository.graphSummaryAt(NOW)).thenReturn(new GraphSummary(0, Optional.empty()));

        var response = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC))
                .getDashboard("request-not-connected");

        var failure = response.metadata().failures().stream()
                .filter(f -> f.section().equals("candidates")).findFirst().orElseThrow();
        assertFalse(failure.retryable());
        assertEquals("이 영역의 원천 데이터를 아직 조회할 수 없습니다.", failure.message());
    }

    @Test
    void failsWholeRequestWhenNoPersistedAreaCanBeRead() {
        when(repository.memberCountsAt(NOW)).thenThrow(new DataAccessResourceFailureException("members unavailable"));
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW))
                .thenThrow(new DataAccessResourceFailureException("audit unavailable"));
        when(repository.graphSummaryAt(NOW)).thenThrow(new DataAccessResourceFailureException("graph unavailable"));

        var service = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC));
        CustomException error = assertThrows(CustomException.class, () -> service.getDashboard("request-3"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        assertTrue(error.isRetryable());
    }

    @Test
    void marksWholeRequestUnavailableAsNonRetryableWhenEveryDatabaseFailureIsNonTransient() {
        var failure = new BadSqlGrammarException("dashboard", "select broken",
                new java.sql.SQLException("syntax error"));
        when(repository.memberCountsAt(NOW)).thenThrow(failure);
        when(repository.auditCountBetween(NOW.minusSeconds(86_400), NOW)).thenThrow(failure);
        when(repository.graphSummaryAt(NOW)).thenThrow(failure);

        var service = new AdminDashboardService(repository, Clock.fixed(NOW, ZoneOffset.UTC));
        CustomException error = assertThrows(CustomException.class, () -> service.getDashboard("request-4"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
        assertFalse(error.isRetryable());
    }
}
