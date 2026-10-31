package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Company;
import com.zoop.graph.version.BriefingGraphLookup;
import com.zoop.graph.version.BriefingGraphUnavailableException;
import com.zoop.graph.version.GraphVersionSelector;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.*;

class BriefingRoundGraphTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;
    private BriefingGraphLookup.Basis basis;
    private GraphQueryService service;

    @BeforeEach @SuppressWarnings("unchecked")
    void setup() {
        basis = new BriefingGraphLookup.Basis("round", "fixture-2026-10-08", NOW, Map.of(HBM_EQUIP, List.of(HANMI)));
        var selector = new GraphVersionSelector(repository(), Clock.fixed(NOW, ZoneOffset.UTC), (id, request) -> basis);
        var reader = new PublicGraphReader(selector, new FixtureGraphSnapshotStore(getClass().getClassLoader()), pinned -> exclusions, null, null);
        var jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.query(anyString(), any(SqlParameterSource.class), any(RowMapper.class))).thenAnswer(call -> {
            List<String> ids = (List<String>) ((SqlParameterSource) call.getArgument(1)).getValue("ids");
            return ids.stream().map(id -> new Company(id, id, null, null)).toList();
        });
        service = new GraphQueryService(reader, jdbc);
    }

    @Test void onlySelectedIssuesAndTheirActualRelatedCompaniesAreShown() {
        var graph = read(null);
        assertEquals(Set.of(HBM_EQUIP), graph.nodes().stream().filter(n -> n.kind().equals("issue")).map(n -> n.id()).collect(java.util.stream.Collectors.toSet()));
        assertTrue(graph.nodes().stream().anyMatch(n -> n.id().equals(HANMI) && n.isFocus()));
        assertTrue(graph.nodes().stream().anyMatch(n -> n.id().equals(HBM_EQUIP) && n.isFocus()));
        assertTrue(graph.nodes().stream().anyMatch(n -> n.id().equals(HYNIX)));
        assertFalse(graph.nodes().stream().anyMatch(n -> n.id().equals(AI_ACCEL) || n.id().equals(NVDA)));
        assertFalse(graph.edges().isEmpty());
        assertEquals("fixture-2026-10-08", graph.metadata().graphVersion());
        assertEquals(NOW.toString(), graph.metadata().asOf());
    }

    @Test void anUnrelatedCompanyCannotExpandTheRoundToTheWholeMarket() {
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class, () -> read(NVDA)).getErrorCode());
        assertEquals(Set.of(HBM_EQUIP), read(HANMI).nodes().stream().filter(n -> n.kind().equals("issue")).map(n -> n.id()).collect(java.util.stream.Collectors.toSet()));
    }

    @Test void withdrawnSelectedIssueOrMissingCompanyRelationCannotBeSilentlyDropped() {
        exclusions = new DisclosureExclusions(1, Set.of(HBM_EQUIP), Set.of(), Set.of());
        assertEquals("briefing_targets_unavailable", assertThrows(BriefingGraphUnavailableException.class, () -> read(null)).reason());
        exclusions = DisclosureExclusions.NONE;
        basis = new BriefingGraphLookup.Basis("round", "fixture-2026-10-08", NOW, Map.of(HBM_EQUIP, List.of(NVDA)));
        assertThrows(BriefingGraphUnavailableException.class, () -> read(null));
    }

    @Test void futureArticlesCannotSupportASelectedIssueBeforeTheCutoff() {
        basis = new BriefingGraphLookup.Basis("round", "fixture-2026-10-08", Instant.parse("2026-10-01T00:00:00Z"), Map.of(AI_ACCEL, List.of(NVDA)));
        assertThrows(BriefingGraphUnavailableException.class, () -> read(null));
    }

    private com.zoop.graph.read.dto.GraphResponse read(String company) {
        return service.getGraph("all", company, null, "round", null, null, null, null, "request");
    }
}
