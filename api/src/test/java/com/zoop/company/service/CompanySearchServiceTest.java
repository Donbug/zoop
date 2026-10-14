package com.zoop.company.service;

import java.time.Instant;
import java.util.List;

import com.zoop.company.repository.CompanySearchRepository;
import com.zoop.company.repository.CompanySearchRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class CompanySearchServiceTest {
    private CompanySearchRepository repository;
    private CompanySearchService service;

    @BeforeEach
    void setUp() {
        repository = mock(CompanySearchRepository.class);
        service = new CompanySearchService(repository, JsonMapper.builder().build());
        when(repository.normalize(anyString())).thenReturn("query");
        when(repository.search(anyString(), any(), any())).thenReturn(List.of());
    }

    @Test
    void maximumIntegerLimitUsesLongLookahead() {
        assertTrue(service.search("query", null, Integer.MAX_VALUE, null, null).items().isEmpty());
        verify(repository).search("query", null, 2147483648L);
    }

    @Test
    void cursorRoundTripPreservesGraphTimeAndLastSortKey() {
        Instant asOf = Instant.parse("2026-10-13T01:02:03.123456Z");
        when(repository.search("query", null, 2L)).thenReturn(List.of(row("a"), row("b")));
        var first = service.search("query", null, 1, "graph-1", asOf);
        assertEquals(List.of("a"), first.items().stream().map(CompanySearchRow::id).toList());
        assertNotNull(first.nextCursor());
        service.search("query", first.nextCursor(), 1, "graph-1", asOf);
        verify(repository).search(eq("query"), argThat(position -> position != null
                && position.rank() == 2 && position.name().equals("a") && position.id().equals("a")), eq(2L));
    }

    @Test
    void cursorCannotBeReusedWithDifferentConditions() {
        Instant asOf = Instant.parse("2026-10-13T00:00:00Z");
        when(repository.search("query", null, 2L)).thenReturn(List.of(row("a"), row("b")));
        String cursor = service.search("query", null, 1, "graph-1", asOf).nextCursor();
        assertThrows(IllegalArgumentException.class, () -> service.search("query", cursor, 2, "graph-1", asOf));
        assertThrows(IllegalArgumentException.class, () -> service.search("query", cursor, 1, "graph-2", asOf));
        assertThrows(IllegalArgumentException.class, () -> service.search("query", cursor, 1, "graph-1", asOf.plusSeconds(1)));
        when(repository.normalize("different")).thenReturn("different");
        assertThrows(IllegalArgumentException.class, () -> service.search("different", cursor, 1, "graph-1", asOf));
    }

    @Test
    void malformedAndEmptyCursorsAreRejected() {
        for (String cursor : List.of("", " ", "!invalid!", "bnVsbA", "e30")) {
            assertThrows(IllegalArgumentException.class, () -> service.search("query", cursor, 1, null, null), cursor);
        }
    }

    @Test
    void nonPositiveLimitIsRejectedBeforeDatabaseAccess() {
        assertThrows(IllegalArgumentException.class, () -> service.search("query", null, 0, null, null));
        assertThrows(IllegalArgumentException.class, () -> service.search("query", null, -1, null, null));
        verifyNoInteractions(repository);
    }

    private static CompanySearchRow row(String id) {
        return new CompanySearchRow(id, null, null, id, null, List.of(), null, null, null, 2);
    }
}
