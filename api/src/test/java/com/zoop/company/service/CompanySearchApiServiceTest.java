package com.zoop.company.service;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import com.zoop.company.graph.CompanyIssueCountQuery;
import com.zoop.company.graph.CompanyIssueCountSnapshot;
import com.zoop.company.repository.CompanySearchPage;
import com.zoop.company.repository.CompanySearchRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class CompanySearchApiServiceTest {
    private CompanySearchService searchService;
    private CompanyIssueCountQuery issueCountQuery;
    private CompanySearchApiService service;

    @BeforeEach
    void setUp() {
        searchService = mock(CompanySearchService.class);
        issueCountQuery = mock(CompanyIssueCountQuery.class);
        service = new CompanySearchApiService(searchService, issueCountQuery);
    }

    @Test
    void composesPostgresSearchWithVersionPinnedIssueCounts() {
        Instant asOf = Instant.parse("2026-10-14T01:00:00Z");
        var row = new CompanySearchRow("company-1", "ZOP", "KOSDAQ", "Zoop", "KR",
                List.of("Zoop Corp"), "#123456", "/logos/zoop.svg", "Tech", 0);
        var page = new CompanySearchPage(List.of(row), "next", null, null, false);
        var pinned = new CompanySearchPage(List.of(row), "pinned-next", "graph-12", asOf, false);
        when(searchService.search("zoop", null, 10, null, null)).thenReturn(page);
        when(issueCountQuery.countIssues(List.of("company-1"), null, null, false))
                .thenReturn(new CompanyIssueCountSnapshot("graph-12", asOf, Map.of("company-1", 3L)));
        when(searchService.pinGraphSnapshot(page, "graph-12", asOf, false)).thenReturn(pinned);

        var response = service.search("zoop", null, 10, null, null, "request-1");

        assertEquals("company-1", response.items().getFirst().id());
        assertEquals(3L, response.items().getFirst().issueCount());
        assertEquals("pinned-next", response.nextCursor());
        assertEquals("graph-12", response.metadata().graphVersion());
        assertEquals(asOf, response.metadata().asOf());
        assertEquals("request-1", response.metadata().requestId());
        assertFalse(response.metadata().partial());
        assertTrue(response.metadata().failures().isEmpty());
    }

    @Test
    void missingGraphCountIsNotReportedAsZero() {
        var row = new CompanySearchRow("company-1", null, null, "Zoop", null,
                List.of(), null, null, null, 2);
        when(searchService.search(null, null, null, null, null))
                .thenReturn(new CompanySearchPage(List.of(row), null, null, null, false));
        when(issueCountQuery.countIssues(List.of("company-1"), null, null, false))
                .thenReturn(new CompanyIssueCountSnapshot("graph-12",
                        Instant.parse("2026-10-14T01:00:00Z"), Map.of()));

        var exception = assertThrows(CustomException.class,
                () -> service.search(null, null, null, null, null, "request-1"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, exception.getErrorCode());
        verify(searchService, never()).pinGraphSnapshot(any(), any(), any(), anyBoolean());
    }
}
