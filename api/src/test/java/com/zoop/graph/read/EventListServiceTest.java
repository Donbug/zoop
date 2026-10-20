package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HANMI;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.dto.EventListResponse;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import tools.jackson.databind.json.JsonMapper;

class EventListServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T00:00:00Z");
    private static final String EUV = "iss-fixture-euv-export";

    private EventListService service;

    @BeforeEach
    void setUp() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), any(SqlParameterSource.class), eq(Integer.class))).thenAnswer(call -> {
            Object id = ((MapSqlParameterSource) call.getArgument(1)).getValue("id");
            return Set.of(HYNIX, HANMI).contains(id) ? 1 : 0;
        });
        service = new EventListService(GraphReadFixtures.reader(NOW, () -> DisclosureExclusions.NONE), jdbc,
                JsonMapper.builder().build());
    }

    private EventListResponse list(String companyId, Integer depth, String from, String to, String cursor, Integer limit) {
        return service.list(companyId, depth, from, to, cursor, limit, null, null);
    }

    private static List<String> ids(List<EventListResponse.EventSummary> items) {
        return items.stream().map(EventListResponse.EventSummary::id).toList();
    }

    @Test
    void wholeGraphNewestFirstWithoutCompanyContext() {
        var r = list(null, 2, null, null, null, null);

        assertEquals(List.of(AI_ACCEL, HBM_EQUIP, HBM_SUPPLY, EUV), ids(r.items()));
        assertEquals(List.of(), r.unknownTimeItems());
        assertTrue(r.items().stream().allMatch(e -> e.relationTypes().isEmpty()));
        assertEquals(List.of("KRX:000660", "NASDAQ:NVDA"), r.items().get(2).companyIds());
        assertEquals(4, r.metadata().total());
        assertEquals("fixture-2026-10-08", r.metadata().graphVersion());
        assertEquals("2026-10-05", r.metadata().latestEventTime());
        assertEquals("2026-10-05T09:00:00Z", r.metadata().latestReportedAt());
        assertNull(r.nextCursor());
    }

    @Test
    void assertionStatusIsTheHandoffIssueStatusAsGiven() {
        var r = list(null, null, null, null, null, null);
        assertEquals(List.of("occurred", "announced", "occurred", "announced"),
                r.items().stream().map(EventListResponse.EventSummary::assertionStatus).toList());
    }

    @Test
    void anEarlierAsOfHidesEventsPublishedAfterIt() {
        // FS040-3 / FS041-4: ai-accel's only article is published 2026-10-05T09:00Z, after this asOf.
        var r = service.list(null, null, null, null, null, null, null, "2026-10-05T00:00:00Z");
        assertFalse(ids(r.items()).contains(AI_ACCEL));
        assertEquals("2026-10-05T00:00:00Z", r.metadata().asOf());
        assertEquals("fixture-2026-10-01", r.metadata().graphVersion());
    }

    @Test
    void aCompanyScopeIsNotCutByTheGraphNodeCap() {
        // 600 issues on one company: the map's 500-node cap would drop the oldest, the timeline keeps every one.
        List<Issue> issues = new java.util.ArrayList<>();
        List<com.zoop.graph.snapshot.PublicGraphSnapshot.Relation> relations = new java.util.ArrayList<>();
        for (int n = 0; n < 600; n++) {
            String id = "iss-" + n;
            issues.add(new Issue(id, "label", null, "unknown", null, null, null, null, "KR", "p", List.of(), List.of(),
                    List.of(), List.of(), null, null));
            relations.add(new com.zoop.graph.snapshot.PublicGraphSnapshot.Relation("rel-" + n, "INVOLVES", id, HYNIX,
                    null, null, List.of(), List.of()));
        }
        var graph = DisplayGraph.of(new com.zoop.graph.snapshot.PublicGraphSnapshot(3, "v", "b",
                List.of(new com.zoop.graph.snapshot.PublicGraphSnapshot.Company(HYNIX, "SK하이닉스", null, null)),
                issues, relations, List.of(), List.of()));
        assertEquals(600, EventListService.companyIssues(graph, HYNIX, 1).size());
    }

    @Test
    void reportedAtIsNeverMadeUpFromADateOnlyPublication() {
        var r = list(null, null, null, null, null, null);
        assertNull(r.items().get(1).reportedAt()); // hbm-equip was published on 2026-09-25 with no time
        assertEquals("2026-10-05T09:00:00Z", r.items().get(0).reportedAt());
    }

    @Test
    void companyScopeFollowsTheTimelineGraphDepthAndReportsOnlyDirectEdges() {
        var hynix = list(HYNIX, 1, null, null, null, null);
        assertEquals(List.of(HBM_EQUIP, HBM_SUPPLY), ids(hynix.items()));
        assertEquals(List.of("STRUCTURALLY_RELATED_TO"), hynix.items().get(0).relationTypes());
        assertEquals(List.of("INVOLVES"), hynix.items().get(1).relationTypes());

        assertEquals(List.of(HBM_EQUIP), ids(list(HANMI, 1, null, null, null, null).items()));
        // Two hops reach the follow-up through FOLLOWS; it is shown, but not as a direct relation of Hanmi.
        var twoHops = list(HANMI, 2, null, null, null, null);
        assertEquals(List.of(HBM_EQUIP, HBM_SUPPLY), ids(twoHops.items()));
        assertEquals(List.of(), twoHops.items().get(1).relationTypes());
    }

    @Test
    void rangeKeepsEventsWhoseApprovedSpanOverlapsIt() {
        // A month-precision event (EUV, 2026-09) overlaps a late-September week; a day outside it does not.
        var r = list(null, null, "2026-09-24", "2026-09-30", null, null);
        assertEquals(List.of(HBM_EQUIP, EUV), ids(r.items()));
        assertEquals(2, r.metadata().total());
        assertEquals(0, r.metadata().excludedUnknownTime());
        // latest* ignore from/to.
        assertEquals("2026-10-05", r.metadata().latestEventTime());
    }

    @Test
    void pagesAreStableOffsetsBoundToTheQuery() {
        var first = list(null, null, null, null, null, 2);
        assertEquals(List.of(AI_ACCEL, HBM_EQUIP), ids(first.items()));
        assertNotNull(first.nextCursor());

        var second = list(null, null, null, null, first.nextCursor(), null);
        assertEquals(List.of(HBM_SUPPLY, EUV), ids(second.items()));
        assertNull(second.nextCursor());
        assertEquals(4, second.metadata().total());

        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> list(HYNIX, null, null, null, first.nextCursor(), null)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> list(null, null, null, null, "not-a-cursor", null)).getErrorCode());
    }

    @Test
    void invalidInputsAreRejectedNotEmptied() {
        for (Runnable bad : List.<Runnable>of(
                () -> list(HYNIX, 3, null, null, null, null),
                () -> list(null, 3, null, null, null, null), // the enum holds even where depth is ignored
                () -> list(null, null, null, null, null, 0),
                () -> list(null, null, "2026-10-02", "2026-10-01", null, null),
                () -> list(null, null, "2026-10-01T00:00:00", null, null, null))) {
            assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class, bad::run).getErrorCode());
        }
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> list("KRX:999999", null, null, null, null, null)).getErrorCode());
    }

    @Test
    void unknownTimeEventsAreMatchedByTheirLatestReportDate() {
        Issue undated = issue(null, "unknown", "2026-09-25T23:30:00Z"); // KST 2026-09-26
        Instant from = Instant.parse("2026-09-25T15:00:00Z"); // KST 09-26 00:00
        Instant to = Instant.parse("2026-09-26T15:00:00Z");
        assertTrue(EventListService.reportedIn(undated, from, to));
        assertFalse(EventListService.reportedIn(undated, to, null));
        assertTrue(EventListService.reportedIn(issue(null, "unknown", "2026-09-26"), from, to));
        assertFalse(EventListService.reportedIn(issue(null, "unknown", null), from, to));
    }

    @Test
    void yearAndExactTimeSpans() {
        Instant from = Instant.parse("2026-06-01T00:00:00Z");
        Instant to = Instant.parse("2026-07-01T00:00:00Z");
        assertTrue(EventListService.overlaps(issue("2026", "year", null), from, to));
        assertFalse(EventListService.overlaps(issue("2025", "year", null), from, to));
        assertTrue(EventListService.overlaps(issue("2026-06-30T23:59:00Z", "datetime", null), from, to));
        assertFalse(EventListService.overlaps(issue("2026-07-01T00:00:00Z", "datetime", null), from, to));
        // An exact to is inclusive (the chart's asOf); a date to runs to the next KST day.
        Instant exactTo = EventListService.bound("2026-07-01T09:00:00+09:00", true);
        assertTrue(EventListService.overlaps(issue("2026-07-01T00:00:00Z", "datetime", null), from, exactTo));
        assertFalse(EventListService.overlaps(issue("2026-07-01T00:00:01Z", "datetime", null), from, exactTo));
        assertEquals(Instant.parse("2026-07-01T15:00:00Z"), EventListService.bound("2026-07-01", true));
    }

    private static Issue issue(String eventTime, String precision, String publishedAt) {
        return new Issue("i", "label", eventTime, precision, null, null, null, null, "KR", "p", List.of(), List.of(),
                List.of(), List.of(), null, publishedAt);
    }
}
