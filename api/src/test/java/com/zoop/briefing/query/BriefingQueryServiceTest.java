package com.zoop.briefing.query;

import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class BriefingQueryServiceTest {
    private final BriefingRoundRepository repository = mock(BriefingRoundRepository.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-13T08:30:00Z"), ZoneOffset.UTC);
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final BriefingQueryService service = new BriefingQueryService(repository, clock, round -> true);
    private final LocalDate date = LocalDate.of(2026, 10, 13);

    private BriefingRound round(String id, String edition, String status) {
        Instant scheduled = Instant.parse(edition.equals("morning") ? "2026-10-13T00:20:00Z" : "2026-10-13T08:30:00Z");
        ObjectNode payload = mapper.createObjectNode().put("id", id).put("date", date.toString()).put("edition", edition)
            .put("scheduledAt", scheduled.toString()).put("generatedAt", scheduled.toString()).put("graphVersion", "g-original").putNull("emptyReason");
        payload.putArray("items").addObject().put("eventId", "fixture-event");
        payload.putObject("references").putArray("eventIds").add("fixture-event");
        payload.putObject("dataWindow").put("end", scheduled.toString());
        payload.putObject("metadata").put("requestId", "old-request").putObject("schedule").put("morning", "07:40");
        payload.putObject("outlook").put("fixture", "stored-outlook");
        payload.putObject("marketVariables").put("fixture", "stored-market");
        ObjectNode snapshot = mapper.createObjectNode(); snapshot.putObject("marketSummary").put("fixture", "stored-summary");
        return new BriefingRound(id, date, edition, scheduled, null, scheduled, true, status,
            status.equals("published") || status.equals("suspended") ? scheduled : null,
            scheduled, "g-original", payload, snapshot, edition.equals("evening") ? mapper.createObjectNode().put("fixture", "stored-comparison") : null);
    }

    @Test void restoresStoredSectionsAndOnlyReplacesTransportRequestId() {
        var row = round("evening", "evening", "published");
        when(repository.find(date, "evening")).thenReturn(Optional.of(row));
        var result = service.get(date, "evening", "current-request");
        assertEquals("g-original", result.path("graphVersion").asString());
        assertEquals("stored-summary", result.path("marketSummary").path("fixture").asString());
        assertEquals("stored-market", result.path("marketVariables").path("fixture").asString());
        assertEquals("stored-comparison", result.path("sinceMorning").path("fixture").asString());
        assertEquals("current-request", result.path("metadata").path("requestId").asString());
        assertEquals("07:40", result.path("metadata").path("schedule").path("morning").asString());
        assertEquals("old-request", row.payload().path("metadata").path("requestId").asString());
    }

    @Test void deniesPublicationWhenCurrentRightsAdapterIsMissing() {
        when(repository.find(date, "morning")).thenReturn(Optional.of(round("morning", "morning", "published")));
        var denied = new BriefingQueryService(repository, clock, r -> false);
        var error = assertThrows(CustomException.class, () -> denied.get(date, "morning", "request"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
    }

    @Test void hidesEveryContentSectionForSuspendedAndUnpublishedRounds() {
        for (String status : List.of("suspended", "scheduled", "missing", "generating", "verifying", "failed")) {
            when(repository.find(date, "morning")).thenReturn(Optional.of(round("morning", "morning", status)));
            var result = service.get(date, "morning", "request");
            assertEquals(0, result.path("items").size()); assertEquals(0, result.path("references").path("eventIds").size());
            assertTrue(result.path("outlook").isNull()); assertTrue(result.path("sinceMorning").isNull());
            assertEquals("unavailable", result.path("marketSummary").path("status").asString());
            assertEquals("unavailable", result.path("marketVariables").path("status").asString());
        }
    }

    @Test void selectsLatestScheduledRoundAtKstBoundaryWithoutCreatingIt() {
        when(repository.find(any(), any())).thenReturn(Optional.empty());
        service.get(null, null, "request"); verify(repository).find(date, "evening");
        var early = new BriefingQueryService(repository, Clock.fixed(Instant.parse("2026-10-13T00:19:59Z"), ZoneOffset.UTC), r -> true);
        var result = early.get(null, null, "request");
        assertEquals("2026-10-12", result.path("date").asString()); assertEquals("evening", result.path("edition").asString());
        assertEquals("09:20", result.path("metadata").path("schedule").path("morning").asString());
        verify(repository, never()).schedule(any(), any(), any(), any(), any(), any());
    }

    @Test void cursorUsesStableKeyAndBindsLimit() {
        var evening = round("evening", "evening", "published"); var morning = round("morning", "morning", "published");
        when(repository.history(null, null, 2)).thenReturn(List.of(evening, morning));
        var first = service.history(null, 1); String cursor = first.path("nextCursor").asString();
        when(repository.history(evening.scheduledAt(), evening.id(), 2)).thenReturn(List.of(morning));
        var second = service.history(cursor, 1);
        assertEquals("morning", second.path("items").get(0).path("id").asString()); assertTrue(second.path("nextCursor").isNull());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () -> service.history(cursor, 2)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () -> service.history("bad", 1)).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class, () -> service.history(null, 0)).getErrorCode());
    }

    @Test void dbOutageIsNotMistakenForNoBriefing() {
        when(repository.find(date, "morning")).thenThrow(new DataAccessResourceFailureException("private db address"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class, () -> service.get(date, "morning", "r")).getErrorCode());
    }
}
