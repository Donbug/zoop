package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static com.zoop.graph.read.GraphReadFixtures.NVDA;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;

class GraphRelationServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;
    private final org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate jdbc =
            org.mockito.Mockito.mock(org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate.class);
    private final GraphRelationService service = new GraphRelationService(GraphReadFixtures.reader(NOW, () -> exclusions), jdbc);

    private static final String STRUCTURAL = DisplayGraph.edgeId("STRUCTURALLY_RELATED_TO", HBM_EQUIP, HYNIX);
    private static final String SHARED = DisplayGraph.edgeId("SHARES_ISSUE", HYNIX, NVDA);

    @Test
    void unknownRoleOnMarketGraphDoesNotImplyABriefingRound() {
        var edge = unknownRoleService().getRelation(
                DisplayGraph.edgeId("INVOLVES", HBM_SUPPLY, HYNIX), null, null, null, "r");
        assertNull(edge.role());
        assertEquals("저장된 기업·사건 연결입니다. 구체적인 역할은 저장된 근거에서 확인해야 합니다.", edge.explanation());
        assertEquals("public_graph_snapshot", edge.metadata().source());
    }

    @Test
    void unknownRoleInAnOriginalBriefingSnapshotKeepsItsRoundContext() {
        var edge = unknownRoleService().getRelation(
                DisplayGraph.edgeId("INVOLVES", HBM_SUPPLY, HYNIX), "round", null, null, "r");
        assertNull(edge.role());
        assertEquals("이 회차에 저장된 기업·사건 연결입니다. 구체적인 역할은 저장된 근거에서 확인해야 합니다.", edge.explanation());
    }

    @Test
    void knownRoleOnMarketGraphKeepsTheConfirmedRoleExplanation() {
        var edge = service.getRelation(DisplayGraph.edgeId("INVOLVES", HBM_SUPPLY, HYNIX), null, null, null, "r");
        assertEquals("공급", edge.role());
        assertEquals(GraphRelationService.EXPLANATIONS.get("INVOLVES"), edge.explanation());
    }

    private GraphRelationService unknownRoleService() {
        var source = GraphReadFixtures.snapshot("fixture-2026-10-08");
        var relations = source.relations().stream().map(r -> new com.zoop.graph.snapshot.PublicGraphSnapshot.Relation(
                r.relationId(), r.relationType(), r.source(), r.target(), null, r.assertionStatus(), r.evidenceIds(), r.basis())).toList();
        var snapshot = new com.zoop.graph.snapshot.PublicGraphSnapshot(source.snapshotFormat(), source.versionId(),
                source.sourceBundleId(), source.companies(), source.issues(), relations, source.articles(), source.evidence());
        var basis = new com.zoop.graph.version.BriefingGraphLookup.Basis("round", source.versionId(), NOW,
                java.util.Map.of(HBM_SUPPLY, List.of(HYNIX, NVDA)));
        var selector = new com.zoop.graph.version.GraphVersionSelector(GraphReadFixtures.repository(),
                java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC), (id, request) -> basis);
        return new GraphRelationService(new PublicGraphReader(selector, ignored -> snapshot, () -> DisclosureExclusions.NONE), jdbc);
    }

    @Test
    @SuppressWarnings("unchecked")
    void aCompanyEndCarriesTheCatalogLogoAndAnIssueEndNone() {
        org.mockito.Mockito.when(jdbc.query(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(org.springframework.jdbc.core.namedparam.SqlParameterSource.class),
                org.mockito.ArgumentMatchers.any(org.springframework.jdbc.core.RowMapper.class)))
                .thenReturn(List.of(new com.zoop.graph.snapshot.PublicGraphSnapshot.Company(HYNIX, "SK하이닉스", "#EA002C",
                        "/graph-assets/sk-hynix.svg")));
        var edge = service.getRelation(STRUCTURAL, null, null, null, "r");
        assertEquals("/graph-assets/sk-hynix.svg", edge.target().logoUrl());
        assertEquals("#EA002C", edge.target().brandColor());
        assertEquals(null, edge.source().logoUrl());
    }

    @Test
    void approvedRelationCarriesItsSourceRelationsBasisAndVerification() {
        var edge = service.getRelation(STRUCTURAL, null, null, null, "r");
        assertEquals("STRUCTURALLY_RELATED_TO", edge.relationType());
        assertTrue(edge.directed());
        assertFalse(edge.derived());
        assertEquals("issue", edge.source().kind());
        assertEquals(HYNIX, edge.target().id());
        assertEquals("company", edge.target().kind());
        assertEquals(List.of("rel-fixture-04"), edge.relationIds());
        // Structural edges carry no role or assertion status in the AI handoff (manual operator basis).
        assertTrue(edge.roles().isEmpty());
        assertNull(edge.role());
        assertEquals("구조적 관계", edge.summary());
        assertEquals("ALLOW", edge.verification().status());
        assertEquals("SUPPLIES", edge.basis().get(0).relationType());
        // Fixture basis valid from 2026-09-01 with no end: active at the request time.
        assertEquals("active", edge.basis().get(0).validity());
        assertEquals("active", edge.validity());
        assertEquals(GraphRelationService.EXPLANATIONS.get("STRUCTURALLY_RELATED_TO"), edge.explanation());
        assertTrue(edge.via().isEmpty());
        assertEquals("fixture-2026-10-08", edge.metadata().graphVersion());
    }

    @Test
    void derivedEdgeIsNotVerifiedAndListsTheSharedIssueWithItsEvidence() {
        var edge = service.getRelation(SHARED, null, null, null, "r");
        assertTrue(edge.derived());
        assertFalse(edge.directed());
        assertEquals("not_applicable", edge.verification().status());
        assertTrue(edge.relationIds().isEmpty());
        assertEquals(GraphRelationService.DERIVED_EXPLANATION, edge.explanation());
        assertEquals(List.of(HBM_SUPPLY), edge.via().stream().map(v -> v.id()).toList());
        // The shared issue's evidence on its links to the two companies.
        assertEquals(2, edge.via().get(0).evidenceIds().size());
        assertNull(edge.role());
        assertNull(edge.validity());
    }

    @Test
    void anEdgeNotVisibleInThisReadIsNotFound() {
        String later = DisplayGraph.edgeId("STRUCTURALLY_RELATED_TO", AI_ACCEL, "NYSE:TSM");
        assertEquals("fixture-2026-10-08", service.getRelation(later, null, null, null, "r").metadata().graphVersion());
        // Before the issue was published (asOf), and once it is withdrawn today.
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.getRelation(later, null, null, "2026-10-05T00:00:00Z", "r")).getErrorCode());
        exclusions = new DisclosureExclusions(2, Set.of(AI_ACCEL), Set.of(), Set.of());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.getRelation(later, null, null, null, "r")).getErrorCode());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.getRelation("edge-0000000000000000", null, null, null, "r")).getErrorCode());
    }

    @Test
    void badSelectorsAreContractErrors() {
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.getRelation(STRUCTURAL, null, null, "yesterday", "r")).getErrorCode());
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class,
                () -> service.getRelation(STRUCTURAL, null, "no-such-version", null, "r")).getErrorCode());
    }
}
