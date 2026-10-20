package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HANMI;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.NVDA;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.dto.GraphResponse;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Company;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class GraphQueryServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private final NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;
    private GraphQueryService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenAnswer(call -> {
            List<String> ids = (List<String>) ((SqlParameterSource) call.getArgument(1)).getValue("ids");
            return ids.stream().filter(id -> id.startsWith("NASDAQ:") || id.startsWith("KRX:") || id.startsWith("NYSE:"))
                    .map(id -> new Company(id, "catalog " + id, null, null)).toList();
        });
        service = new GraphQueryService(GraphReadFixtures.reader(NOW, () -> exclusions), jdbc);
    }

    private GraphResponse all() {
        return service.getGraph(null, null, null, null, null, null, null, null, "req-1");
    }

    private static Set<String> nodeIds(GraphResponse r) {
        return r.nodes().stream().map(GraphResponse.Node::id).collect(java.util.stream.Collectors.toSet());
    }

    @Test
    void wholeMarketGraphFromTheActiveVersionWithoutPersonalData() {
        GraphResponse r = all();
        assertEquals("fixture-2026-10-08", r.metadata().graphVersion());
        assertEquals("all", r.metadata().mode());
        assertEquals(NOW.toString(), r.metadata().asOf());
        assertEquals(List.of(), r.metadata().focusCompanyIds());
        assertNull(r.metadata().emptyReason());
        assertTrue(nodeIds(r).containsAll(Set.of(HBM_SUPPLY, AI_ACCEL, NVDA)));
        assertTrue(r.nodes().stream().noneMatch(n -> n.holding() || n.watch() || n.isFocus()));
        assertTrue(r.edges().stream().anyMatch(e -> e.relationType().equals("SHARES_ISSUE") && e.derived()));
        var issue = r.nodes().stream().filter(n -> n.id().equals(HBM_SUPPLY)).findFirst().orElseThrow();
        assertEquals("international", issue.geography());
        assertEquals(2, issue.evidenceCount());
        assertEquals("day", issue.timePrecision());
    }

    @Test
    void asOfPinsTheThenActiveVersionAndHidesLaterArticles() {
        GraphResponse r = service.getGraph("all", null, null, null, null, "2026-10-05T00:00:00Z", null, null, "req-2");
        assertEquals("fixture-2026-10-01", r.metadata().graphVersion());
        assertEquals("2026-10-05T00:00:00Z", r.metadata().asOf());
        assertFalse(nodeIds(r).contains(AI_ACCEL));
    }

    @Test
    void focusCompanyWithDepthOneReturnsItsIssuesAndTheirCompaniesOnly() {
        GraphResponse r = service.getGraph("all", HANMI, 1, null, null, null, null, null, "req-3");
        assertEquals(List.of(HANMI), r.metadata().focusCompanyIds());
        assertEquals(1, r.metadata().depth());
        assertTrue(nodeIds(r).contains(HBM_EQUIP));
        assertTrue(r.nodes().stream().anyMatch(n -> n.id().equals(HANMI) && n.isFocus()));
        assertFalse(nodeIds(r).contains(AI_ACCEL));
    }

    @Test
    void catalogCompanyMissingFromTheVersionIsKeptWithNoRelations() {
        GraphResponse r = service.getGraph("all", "KRX:035420", null, null, null, null, null, null, "req-4");
        assertEquals(1, r.nodes().size());
        assertTrue(r.nodes().get(0).isFocus());
        assertEquals("no_related_issues", r.metadata().emptyReason());
    }

    @Test
    void currentExclusionsHideTheIssueAndItsDerivedEdges() {
        exclusions = new DisclosureExclusions(2, Set.of(HBM_SUPPLY), Set.of(), Set.of());
        GraphResponse r = all();
        assertFalse(nodeIds(r).contains(HBM_SUPPLY));
        assertTrue(r.edges().stream().noneMatch(e -> e.via().contains(HBM_SUPPLY)));
    }

    @Test
    void errorsAreNeverAnEmptyGraph() {
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, failure("all", "ORG:NOPE", null, null));
        assertEquals(ErrorCode.INVALID_REQUEST, failure("all", null, 0, null));
        assertEquals(ErrorCode.INVALID_REQUEST, failure("everything", null, null, null));
        assertEquals(ErrorCode.INVALID_REQUEST, failure("all", null, null, "yesterday"));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure("all", null, null, "2026-09-01T00:00:00Z"));
    }

    private static final String HYNIX = "KRX:000660";
    private static final PersonalCompanies.Ids MINE = new PersonalCompanies.Ids(List.of(HYNIX), List.of(NVDA, "ORG:STALE"));

    @Test
    void personalModeCentresOnTheMembersHoldingsAndWatchlist() {
        GraphResponse r = service.getGraph("personal", null, 1, null, null, null, null, MINE, "p1");
        assertEquals("personal", r.metadata().mode());
        assertEquals("all", r.metadata().personalFilter());
        // A watchlist id the catalog no longer knows is left out instead of failing the graph.
        assertEquals(List.of(HYNIX, NVDA), r.metadata().focusCompanyIds());
        var hynix = r.nodes().stream().filter(n -> n.id().equals(HYNIX)).findFirst().orElseThrow();
        var nvda = r.nodes().stream().filter(n -> n.id().equals(NVDA)).findFirst().orElseThrow();
        assertTrue(hynix.holding() && hynix.isFocus() && !hynix.watch());
        assertTrue(nvda.watch() && !nvda.holding());
    }

    @Test
    void personalFilterNarrowsTheFocusAndCompanyIdRecentres() {
        assertEquals(List.of(NVDA), service.getGraph("personal", null, 1, null, null, null, "watchlist", MINE, "p")
                .metadata().focusCompanyIds());
        assertEquals(List.of(HYNIX), service.getGraph("personal", null, 1, null, null, null, "holdings", MINE, "p")
                .metadata().focusCompanyIds());
        GraphResponse centred = service.getGraph("personal", HANMI, 1, null, null, null, null, MINE, "p");
        assertEquals(List.of(HANMI), centred.metadata().focusCompanyIds());
        assertTrue(centred.nodes().stream().filter(n -> n.id().equals(HYNIX)).allMatch(GraphResponse.Node::holding));
    }

    @Test
    void personalModeWithoutOwnCompaniesSaysSo() {
        GraphResponse r = service.getGraph("personal", null, null, null, null, null, null,
                new PersonalCompanies.Ids(List.of(), List.of()), "p");
        assertTrue(r.nodes().isEmpty());
        assertEquals("no_personal_stocks", r.metadata().emptyReason());
        assertEquals("fixture-2026-10-08", r.metadata().graphVersion());
    }

    @Test
    void personalModeRefusesARoundAndAnUnknownFilter() {
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.getGraph("personal", null, null, "brf-1", null, null, null, MINE, "p")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.getGraph("personal", null, null, null, null, null, "friends", MINE, "p")).getErrorCode());
    }

    @Test
    void allModeIgnoresPersonalFilterEvenAnUnknownValue() {
        assertEquals("all", service.getGraph("all", null, null, null, null, null, "friends", null, "r").metadata().mode());
    }

    @Test
    void allModeCarriesNoPersonalFlags() {
        assertTrue(all().nodes().stream().noneMatch(n -> n.holding() || n.watch()));
        assertNull(all().metadata().personalFilter());
    }

    @Test
    void companyGraphAsOfCountsLiteralEdgesFromTheCompany() {
        String at = "2026-10-12T09:00:00+09:00";
        GraphResponse one = service.getCompanyGraphAsOf(HANMI, at, null, null, "r1");
        assertEquals(Set.of(HANMI, HBM_EQUIP), nodeIds(one));
        assertEquals(1, one.metadata().depth());
        assertEquals(List.of(HANMI), one.metadata().focusCompanyIds());
        // Two edges reach the issue's other company and the issue it is followed by, not that issue's companies.
        GraphResponse two = service.getCompanyGraphAsOf(HANMI, at, 2, null, "r2");
        assertEquals(Set.of(HANMI, HBM_EQUIP, "KRX:000660", HBM_SUPPLY), nodeIds(two));
        assertTrue(two.edges().stream().noneMatch(e -> e.derived() && !nodeIds(two).containsAll(e.via())));
    }

    @Test
    void companyGraphAsOfPinsTheVersionActiveAtThatTime() {
        GraphResponse past = service.getCompanyGraphAsOf(NVDA, "2026-10-05T00:00:00Z", 1, null, "r");
        assertEquals("fixture-2026-10-01", past.metadata().graphVersion());
        assertEquals("2026-10-05T00:00:00Z", past.metadata().asOf());
        assertEquals("all", past.metadata().mode());
    }

    @Test
    void companyGraphAsOfRejectsWhatTheContractDoesNotAllow() {
        for (String asOf : new String[] {null, "", "2026-10-05", "2026-10-05T00:00:00"}) {
            assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                    () -> service.getCompanyGraphAsOf(NVDA, asOf, 1, null, "r")).getErrorCode(), String.valueOf(asOf));
        }
        for (int depth : new int[] {0, 3}) {
            assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                    () -> service.getCompanyGraphAsOf(NVDA, "2026-10-12T00:00:00Z", depth, null, "r")).getErrorCode());
        }
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.getCompanyGraphAsOf("ORG:NOPE", "2026-10-12T00:00:00Z", 1, null, "r")).getErrorCode());
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service.getCompanyGraphAsOf(NVDA, "2026-09-01T00:00:00Z", 1, null, "r")).getErrorCode());
    }

    @Test
    void unreadableSnapshotIsSourceUnavailable() {
        var broken = new GraphQueryService(new PublicGraphReader(new GraphVersionSelector(new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.empty(); }
            public Optional<GraphVersionRecord> active() {
                return Optional.of(new GraphVersionRecord("v", 1, "fixture", "a", FixtureGraphSnapshotStore.URI_PREFIX + "gone.json", "0".repeat(64), true));
            }
            public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.empty(); }
            public boolean everActivated(String id) { return false; }
        }, Clock.fixed(NOW, ZoneOffset.UTC)), new FixtureGraphSnapshotStore(getClass().getClassLoader()), () -> exclusions), jdbc);
        assertThrows(GraphSnapshotUnavailableException.class, () -> broken.getGraph(null, null, null, null, null, null, null, null, "r"));
    }

    private ErrorCode failure(String mode, String companyId, Integer depth, String asOf) {
        return assertThrows(CustomException.class,
                () -> service.getGraph(mode, companyId, depth, null, null, asOf, null, null, "req")).getErrorCode();
    }
}
