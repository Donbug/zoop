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

    private static GraphVersionRecord record(String id, boolean active) {
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(GraphReadFixtures.bytes(id)), active);
    }

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        Map<String, GraphVersionRecord> versions = Map.of("fixture-2026-10-01", record("fixture-2026-10-01", false),
                "fixture-2026-10-08", record("fixture-2026-10-08", true));
        GraphVersionRepository repository = new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(versions.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(versions.get("fixture-2026-10-08")); }
            public Optional<String> activeVersionIdAt(Instant asOf) {
                if (asOf.isBefore(Instant.parse("2026-10-01T00:00:00Z"))) return Optional.empty();
                return Optional.of(asOf.isBefore(Instant.parse("2026-10-08T00:00:00Z")) ? "fixture-2026-10-01" : "fixture-2026-10-08");
            }
            public boolean everActivated(String id) { return versions.containsKey(id); }
        };
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenAnswer(call -> {
            String id = (String) ((SqlParameterSource) call.getArgument(1)).getValue("id");
            return id.startsWith("NASDAQ:") || id.startsWith("KRX:") || id.startsWith("NYSE:")
                    ? List.of(new Company(id, "catalog " + id, null, null)) : List.of();
        });
        service = new GraphQueryService(new GraphVersionSelector(repository, Clock.fixed(NOW, ZoneOffset.UTC)),
                new FixtureGraphSnapshotStore(getClass().getClassLoader()), () -> exclusions, jdbc);
    }

    private GraphResponse all() {
        return service.getGraph(null, null, null, null, null, null, "req-1");
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
        GraphResponse r = service.getGraph("all", null, null, null, null, "2026-10-05T00:00:00Z", "req-2");
        assertEquals("fixture-2026-10-01", r.metadata().graphVersion());
        assertEquals("2026-10-05T00:00:00Z", r.metadata().asOf());
        assertFalse(nodeIds(r).contains(AI_ACCEL));
    }

    @Test
    void focusCompanyWithDepthOneReturnsItsIssuesAndTheirCompaniesOnly() {
        GraphResponse r = service.getGraph("all", HANMI, 1, null, null, null, "req-3");
        assertEquals(List.of(HANMI), r.metadata().focusCompanyIds());
        assertEquals(1, r.metadata().depth());
        assertTrue(nodeIds(r).contains(HBM_EQUIP));
        assertTrue(r.nodes().stream().anyMatch(n -> n.id().equals(HANMI) && n.isFocus()));
        assertFalse(nodeIds(r).contains(AI_ACCEL));
    }

    @Test
    void catalogCompanyMissingFromTheVersionIsKeptWithNoRelations() {
        GraphResponse r = service.getGraph("all", "KRX:035420", null, null, null, null, "req-4");
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
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure("personal", null, null, null));
    }

    @Test
    void unreadableSnapshotIsSourceUnavailable() {
        var broken = new GraphQueryService(new GraphVersionSelector(new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.empty(); }
            public Optional<GraphVersionRecord> active() {
                return Optional.of(new GraphVersionRecord("v", 1, "fixture", "a", FixtureGraphSnapshotStore.URI_PREFIX + "gone.json", "0".repeat(64), true));
            }
            public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.empty(); }
            public boolean everActivated(String id) { return false; }
        }, Clock.fixed(NOW, ZoneOffset.UTC)), new FixtureGraphSnapshotStore(getClass().getClassLoader()), () -> exclusions, jdbc);
        assertThrows(GraphSnapshotUnavailableException.class, () -> broken.getGraph(null, null, null, null, null, null, "r"));
    }

    private ErrorCode failure(String mode, String companyId, Integer depth, String asOf) {
        return assertThrows(CustomException.class,
                () -> service.getGraph(mode, companyId, depth, null, null, asOf, "req")).getErrorCode();
    }
}
