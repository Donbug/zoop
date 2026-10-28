package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class CompanyIssueImpactServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private final EvidenceService evidence = mock(EvidenceService.class);
    private final CompanyIssueImpactService service = new CompanyIssueImpactService(
            GraphReadFixtures.reader(NOW, ignored -> DisclosureExclusions.NONE), evidence);

    @Test
    void returnsOnlyEvidenceFromTheVisibleDirectInvolvesRelation() {
        var relation = GraphReadFixtures.snapshot("fixture-2026-10-08").relations().stream()
                .filter(r -> "INVOLVES".equals(r.relationType()) && HBM_SUPPLY.equals(r.source())
                        && HYNIX.equals(r.target()))
                .findFirst().orElseThrow();
        relation.evidenceIds().forEach(id -> when(evidence.shownNow(eq(id), eq(null),
                eq("fixture-2026-10-08"), eq(null), eq("req-1"))).thenReturn(true));

        var result = service.getImpact(HYNIX, HBM_SUPPLY, null, null, null, "req-1");

        assertEquals(List.of(HBM_SUPPLY, HYNIX), result.steps().stream().map(s -> s.id()).toList());
        assertEquals(List.of("issue", "company"), result.steps().stream().map(s -> s.kind()).toList());
        assertEquals(relation.evidenceIds(), result.steps().get(0).evidenceIds());
        assertEquals("fixture-2026-10-08", result.metadata().graphVersion());
        assertFalse(result.metadata().partial());
    }

    @Test
    void returnsAnEmptyPathWhenVisibleNodesHaveNoDirectRelation() {
        var result = service.getImpact(HYNIX, HBM_EQUIP, null, null, null, "req-2");

        assertTrue(result.steps().isEmpty());
        assertFalse(result.metadata().partial());
        org.mockito.Mockito.verifyNoInteractions(evidence);
    }

    @Test
    void removesEvidenceWithWithdrawnRightsAndMarksThePartialResponse() {
        var relation = GraphReadFixtures.snapshot("fixture-2026-10-08").relations().stream()
                .filter(r -> "INVOLVES".equals(r.relationType()) && HBM_SUPPLY.equals(r.source())
                        && HYNIX.equals(r.target()))
                .findFirst().orElseThrow();
        when(evidence.shownNow(eq(relation.evidenceIds().get(0)), eq(null), eq("fixture-2026-10-08"),
                eq(null), eq("req-3"))).thenReturn(false);
        relation.evidenceIds().stream().skip(1).forEach(id -> when(evidence.shownNow(eq(id), eq(null),
                eq("fixture-2026-10-08"), eq(null), eq("req-3"))).thenReturn(true));

        var result = service.getImpact(HYNIX, HBM_SUPPLY, null, null, null, "req-3");

        assertTrue(result.metadata().partial());
        assertEquals("EVIDENCE_UNAVAILABLE", result.metadata().failures().get(0).code());
        assertFalse(result.steps().get(0).evidenceIds().contains(relation.evidenceIds().get(0)));
    }

    @Test
    void appliesAnExplicitAsOfToTheCurrentRightsCheck() {
        var relation = GraphReadFixtures.snapshot("fixture-2026-10-08").relations().stream()
                .filter(r -> "INVOLVES".equals(r.relationType()) && HBM_SUPPLY.equals(r.source())
                        && HYNIX.equals(r.target()))
                .findFirst().orElseThrow();
        Instant asOf = Instant.parse("2026-10-15T00:00:00Z");
        relation.evidenceIds().forEach(id -> when(evidence.shownNow(eq(id), eq(null),
                eq("fixture-2026-10-08"), eq(asOf), eq("req-6"))).thenReturn(true));

        service.getImpact(HYNIX, HBM_SUPPLY, null, null, "2026-10-15T00:00:00Z", "req-6");

        org.mockito.Mockito.verify(evidence).shownNow(eq(relation.evidenceIds().get(0)), eq(null),
                eq("fixture-2026-10-08"), eq(asOf), eq("req-6"));
    }

    @Test
    void propagatesAnUnavailableRightsSourceInsteadOfReturningAnEmptyPath() {
        String evidenceId = GraphReadFixtures.snapshot("fixture-2026-10-08").relations().stream()
                .filter(r -> "INVOLVES".equals(r.relationType()) && HBM_SUPPLY.equals(r.source())
                        && HYNIX.equals(r.target()))
                .findFirst().orElseThrow().evidenceIds().get(0);
        when(evidence.shownNow(eq(evidenceId), eq(null), eq("fixture-2026-10-08"), eq(null), eq("req-7")))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));

        var error = assertThrows(CustomException.class,
                () -> service.getImpact(HYNIX, HBM_SUPPLY, null, null, null, "req-7"));

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
    }

    @Test
    void doesNotExposeGraphNodesOutsideTheSelectedSnapshot() {
        var error = assertThrows(CustomException.class,
                () -> service.getImpact(HYNIX, "iss-not-visible", null, null, null, "req-4"));
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, error.getErrorCode());
    }

    @Test
    void rejectsMalformedAsOf() {
        var error = assertThrows(CustomException.class,
                () -> service.getImpact(HYNIX, HBM_SUPPLY, null, null, "yesterday", "req-5"));
        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
    }
}
