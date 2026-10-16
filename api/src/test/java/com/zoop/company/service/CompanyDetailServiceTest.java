package com.zoop.company.service;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.graph.CompanyGraphSnapshot;
import com.zoop.company.graph.CompanyGraphSnapshotReader;
import com.zoop.company.repository.CompanyProfileRow;
import com.zoop.company.repository.CompanySearchRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class CompanyDetailServiceTest {
    private CompanySearchRepository repository;
    private CompanyGraphSnapshotReader graphReader;
    private CompanyDetailService service;

    @BeforeEach
    void setUp() {
        repository = mock(CompanySearchRepository.class);
        graphReader = mock(CompanyGraphSnapshotReader.class);
        service = new CompanyDetailService(repository, graphReader);
        when(repository.findProfile("company-1")).thenReturn(Optional.of(profile()));
    }

    @Test
    void noPublishedSnapshotReturnsPartialProfileWithUnavailableGraphSections() {
        when(graphReader.read(any())).thenReturn(Optional.empty());

        var result = service.getCompany("company-1", null, null, null, "req-1");

        assertEquals("company-1", result.id());
        assertTrue(result.directIssues().isEmpty());
        assertInstanceOf(CompanyDetailService.Unavailable.class, result.summary());
        assertTrue(result.metadata().partial());
        assertNull(result.metadata().graphVersion());
        assertNotNull(result.metadata().asOf());
        assertEquals(3, result.metadata().failures().size());
    }

    @Test
    void requestedPinnedSnapshotWithoutMatchIsAConflictRatherThanAnEmptyGraph() {
        when(graphReader.read(any())).thenReturn(Optional.empty());

        var error = assertThrows(CustomException.class,
                () -> service.getCompany("company-1", null, "graph-v7", null, "req-1"));

        assertEquals(ErrorCode.VERSION_UNAVAILABLE, error.getErrorCode());
    }

    @Test
    void snapshotSuppliesVersionAsOfIssuesAndSummaryForResponse() {
        var issue = new CompanyGraphSnapshot.CompanyIssueRef("Issue", "event-1", null, null, "direct",
                "confirmed", 2, List.of());
        var snapshot = new CompanyGraphSnapshot("graph-v7", Instant.parse("2026-10-15T12:00:00Z"), true,
                List.of(issue), List.of(), new CompanyGraphSnapshot.Summary("Summary", List.of("evidence-1"),
                        Instant.parse("2026-10-15T12:00:00Z"), "analysis-v2"));
        when(graphReader.read(any())).thenReturn(Optional.of(snapshot));

        var result = service.getCompany("company-1", null, null, null, "req-1");

        assertEquals(List.of(issue), result.directIssues());
        assertEquals("graph-v7", result.metadata().graphVersion());
        assertEquals(snapshot.asOf(), result.metadata().asOf());
        assertEquals("public_graph_snapshot", result.metadata().source());
        assertEquals("Summary", ((CompanyGraphSnapshot.Summary) result.summary()).text());
        assertFalse(result.metadata().partial());
    }

    @Test
    void graphMissingTheCompanyKeepsTheCatalogProfileAndReturnsAnEmptyGraphView() {
        var snapshot = new CompanyGraphSnapshot("graph-v7", Instant.parse("2026-10-15T12:00:00Z"), false,
                List.of(), List.of(), null);
        when(graphReader.read(any())).thenReturn(Optional.of(snapshot));

        var result = service.getCompany("company-1", null, null, null, "req-1");

        assertEquals("company-1", result.id());
        assertTrue(result.directIssues().isEmpty());
        assertTrue(result.structuralIssues().isEmpty());
        assertInstanceOf(CompanyDetailService.Unavailable.class, result.summary());
        assertEquals("graph-v7", result.metadata().graphVersion());
        assertEquals("GRAPH_COMPANY_NOT_FOUND", result.metadata().failures().getFirst().code());
    }

    @Test
    void invalidAsOfIsRejectedAsInvalidRequest() {
        var error = assertThrows(CustomException.class,
                () -> service.getCompany("company-1", null, null, "not-an-instant", "req-1"));
        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
    }

    private static CompanyProfileRow profile() {
        return new CompanyProfileRow("company-1", "Company", "Legal Co", "KRX", "Representative", null,
                null, null, null, null, null, "https://example.test", "Technology");
    }
}
