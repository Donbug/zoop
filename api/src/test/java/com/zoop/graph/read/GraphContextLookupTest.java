package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static com.zoop.graph.read.GraphReadFixtures.NVDA;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;

class GraphContextLookupTest {
    private static final String SUPPLY_NVDA = "ev-912843a071ee90c12ee7e909c65f06ce748d2a35c7c29c6c871faac130e4f395";
    private static final String SUPPLY_HYNIX = "ev-bb3008cb36e9b51c0d2fd77af059259332b1887cc04862e185a496c3dcc9e421";
    private static final String EQUIP_HYNIX = "ev-fd9d18853fde470f24184b7db11e534270c580072fc0ca877323825a751c94bf";

    private final GraphContextLookup lookup = new GraphContextLookup(
            DisplayGraph.of(GraphReadFixtures.snapshot("fixture-2026-10-08")));

    @Test
    void companyCarriesTheEvidenceOfItsApprovedRelations() {
        var company = lookup.find(HYNIX).orElseThrow();
        assertEquals("company", company.kind());
        assertEquals("SK하이닉스", company.label());
        assertEquals(List.of(HYNIX), company.companyIds());
        assertEquals(Set.of(SUPPLY_HYNIX, EQUIP_HYNIX), Set.copyOf(company.evidenceIds()));
    }

    @Test
    void issueCarriesItsCompaniesAndEvidence() {
        var issue = lookup.find(HBM_SUPPLY).orElseThrow();
        assertEquals("issue", issue.kind());
        assertEquals(Set.of(NVDA, HYNIX), Set.copyOf(issue.companyIds()));
        assertEquals(Set.of(SUPPLY_NVDA, SUPPLY_HYNIX), Set.copyOf(issue.evidenceIds()));
    }

    @Test
    void sharedIssueEdgeRestsOnTheEvidenceOfTheIssuesItGoesThrough() {
        var edge = lookup.find(DisplayGraph.edgeId("SHARES_ISSUE", HYNIX, NVDA)).orElseThrow();
        assertEquals("edge", edge.kind());
        assertEquals("SK하이닉스 – NVIDIA", edge.label());
        assertEquals(Set.of(HYNIX, NVDA), Set.copyOf(edge.companyIds()));
        assertEquals(Set.of(SUPPLY_NVDA, SUPPLY_HYNIX), Set.copyOf(edge.evidenceIds()));
    }

    @Test
    void evidenceIsLabelledWithItsArticleTitle() {
        var evidence = lookup.find(SUPPLY_NVDA).orElseThrow();
        assertEquals("evidence", evidence.kind());
        assertEquals("[합성] HBM 공급 계약 보도", evidence.label());
        assertEquals(List.of(SUPPLY_NVDA), evidence.evidenceIds());
    }

    @Test
    void unknownAndExcludedTargetsAreNotFound() {
        assertTrue(lookup.find("KRX:999999").isEmpty());
        var visible = GraphSnapshotFilter.apply(GraphReadFixtures.snapshot("fixture-2026-10-08"), null,
                new DisclosureExclusions(1, Set.of(HBM_SUPPLY), Set.of(), Set.of()));
        var filtered = new GraphContextLookup(DisplayGraph.of(visible));
        assertTrue(filtered.find(HBM_SUPPLY).isEmpty());
        assertTrue(filtered.find(HYNIX).orElseThrow().evidenceIds().stream()
                .noneMatch(id -> id.equals(SUPPLY_HYNIX)));
    }
}
