package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static com.zoop.graph.read.GraphReadFixtures.NVDA;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;

class DisplayGraphTest {
    private final DisplayGraph graph = DisplayGraph.of(GraphReadFixtures.snapshot("fixture-2026-10-08"));

    @Test
    void displayEdgeIdIsStableAcrossVersionsAndIndependentOfRelationIds() {
        String id = DisplayGraph.edgeId("INVOLVES", HBM_SUPPLY, NVDA);
        var edge = graph.edges.get(id);
        assertEquals(List.of("rel-fixture-01"), edge.relationIds());
        assertEquals(id, DisplayGraph.of(GraphReadFixtures.snapshot("fixture-2026-10-01")).edges.get(id).id());
        assertTrue(id.matches("edge-[0-9a-f]{16}"));
    }

    @Test
    void companiesSharingAnIssueGetADerivedEdgeWithoutEvidence() {
        var shared = graph.edges.get(DisplayGraph.edgeId("SHARES_ISSUE", HYNIX, NVDA));
        assertTrue(shared.derived());
        assertEquals(List.of(HBM_SUPPLY), shared.via());
        assertTrue(shared.evidenceIds().isEmpty());
        assertEquals("같은 사건 1건", shared.summary());
    }

    @Test
    void derivedEdgesAreComputedAfterFilteringNotStored() {
        var visible = GraphSnapshotFilter.apply(GraphReadFixtures.snapshot("fixture-2026-10-08"), null,
                new DisclosureExclusions(1, Set.of(HBM_SUPPLY), Set.of(), Set.of()));
        assertTrue(DisplayGraph.of(visible).edges.values().stream()
                .noneMatch(e -> e.derived() && e.via().contains(HBM_SUPPLY)));
    }
}
