package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.*;
import com.zoop.common.json.StrictJson;
import com.zoop.company.graph.CompanyGraphReadRequest;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

class BriefingReconstructedDetailsTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private final BriefingQueryService publications = mock(BriefingQueryService.class);
    private final BriefingRoundRepository rounds = mock(BriefingRoundRepository.class);
    private PublicGraphReader reader() {
        var source = snapshot("fixture-2026-10-08");
        var rels = source.relations().stream().map(r -> new PublicGraphSnapshot.Relation(r.relationId(), r.relationType(),
                r.source(), r.target(), null, r.assertionStatus(), r.evidenceIds(), r.basis())).toList();
        var snapshot = new PublicGraphSnapshot(source.snapshotFormat(), source.versionId(), source.sourceBundleId(),
                source.companies(), source.issues(), rels, source.articles(), source.evidence());
        var version = record(source.versionId(), false);
        var basis = new BriefingGraphLookup.Basis("round", source.versionId(), NOW, Map.of(HBM_SUPPLY, List.of(HYNIX, NVDA)),
                new BriefingGraphLookup.Reconstruction(version, NOW));
        return new PublicGraphReader(new GraphVersionSelector(repository(), Clock.fixed(NOW, ZoneOffset.UTC),
                (id, request) -> basis), ignored -> snapshot, pinned -> DisclosureExclusions.NONE);
    }
    @Test void relationCompanyAndEventKeepReconstructedSourceAndUnknownRole() {
        var reader = reader();
        var detail = new GraphRelationService(reader, mock(NamedParameterJdbcTemplate.class)).getRelation(
                DisplayGraph.edgeId("INVOLVES", HBM_SUPPLY, HYNIX), "round", null, null, "r");
        assertEquals("briefing_reconstructed_graph", detail.metadata().source());
        assertEquals("not_applicable", detail.verification().status());
        assertNull(detail.role());
        assertFalse(detail.explanation().contains("직접 적혀"));
        assertEquals("briefing_reconstructed_graph", new GraphCompanySnapshotReader(reader)
                .read(new CompanyGraphReadRequest(HYNIX, "round", null, null)).orElseThrow().source());
        assertEquals("briefing_reconstructed_graph", new EventDetailService(reader, mock(com.zoop.document.evidence.service.EvidenceService.class),
                mock(com.zoop.document.repository.DocumentRegistryRepository.class)).get(HBM_SUPPLY, "round", null, null, "r").metadata().source());
    }
    @Test void preservedEvidenceKeepsExactOffsetsRoundAndSourceAndNeverUsesAnImportReceipt() {
        var reader = reader();
        var span = reader.read("round", null, null).graph().snapshot.evidence().getFirst();
        var detail = StrictJson.newObject();
        detail.putArray("evidence").addObject().put("id", span.evidenceId()).put("documentId", span.articleId())
                .put("documentVersion", span.articleVersion()).put("title", "보존 원문").put("publisher", "발행자")
                .put("url", "https://example.invalid/a").put("publishedAt", NOW.minusSeconds(100).toString()).put("quote", "정확 인용");
        when(publications.getItem("round", HBM_SUPPLY, "r")).thenReturn(detail);
        var saved = new BriefingRoundRepository.ItemEvidence(span.evidenceId(), span.articleId(), span.articleVersion(), "정확 인용",
                span.start(), span.end(), "보존 원문", "발행자", "https://example.invalid/a", NOW.minusSeconds(100), "news", "a".repeat(64));
        when(rounds.findItemEvidence(span.evidenceId())).thenReturn(Optional.of(saved));
        var port = new GraphEvidenceSnapshotReader(reader, publications, rounds);
        var result = port.readRound("round", null, null, span.evidenceId(), null, "r").preserved();
        assertEquals("정확 인용", result.quote()); assertEquals(span.start(), result.start());
        assertEquals("briefing_reconstructed_graph", result.metadata().source());
        assertEquals(List.of(HBM_SUPPLY), result.eventIds());
        when(rounds.findItemEvidence(span.evidenceId())).thenReturn(Optional.of(new BriefingRoundRepository.ItemEvidence(
                saved.id(), saved.documentId(), saved.documentVersion(), saved.quote(), saved.start()+1, saved.end(), saved.title(),
                saved.publisher(), saved.url(), saved.publishedAt(), saved.sourceKind(), saved.bodySha256())));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> port.readRound("round", null, null, span.evidenceId(), null, "r")).getErrorCode());
        when(publications.getItem("round", HBM_SUPPLY, "r")).thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        assertThrows(CustomException.class, () -> port.readRound("round", null, null, span.evidenceId(), null, "r"));
    }
}
